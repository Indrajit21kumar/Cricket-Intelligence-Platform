"""Accuracy gate + snapshot regression + release gating (M11 Step 8, §14, ENG-007).

Three release gates, all blocking, so an unvalidated or regressing estimation
model cannot ship (AC-M11-07, NFR-M11-04):

**Accuracy vs ground truth (§14).** A model change MUST NOT regress mean absolute
error beyond the per-quantity-class tolerance bands. The bands differ by class
and by how the estimate is judged: velocity / momentum / torque / energy / force
are relative (a fraction of truth, because their magnitudes span a wide range),
while angles / distances / ratios / timing are absolute. Error accumulates PER
QUANTITY across the golden set and each quantity's MAE is checked against its
class band — pooling per class would let one systematically-wrong quantity hide
behind its well-behaved neighbours (the same trap M10's gate was built to avoid).

**Determinism (NFR-M11-02, AC-M11-08).** The physics is pure arithmetic, so
identical input must give byte-identical output. Any drift is a regression.

**Release gate (ENG-007).** A version serves in production only if it is
registered AND validated (:mod:`models`) AND its accuracy passes. An unvalidated
model is blocked even with perfect accuracy; a regressing model is blocked even
if validated.

The ground-truth corpus (force-plate / sensor-fused strokes, §14) is a data
workstream that does not exist yet. The gate is built and tested against
labelled fixture reports and wired into CI, so it starts blocking the moment
real validation data lands.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.biomech_input import BiomechanicsInput
from physics_service.domain.models import is_production_ready
from physics_service.domain.quantities import (
    CATALOGUE,
    CLASS_ANGLE,
    CLASS_ANGULAR_VELOCITY,
    CLASS_DISTANCE,
    CLASS_ENERGY,
    CLASS_FORCE,
    CLASS_LINEAR_VELOCITY,
    CLASS_MOMENTUM,
    CLASS_RATIO,
    CLASS_TIMING,
    CLASS_TORQUE,
)
from physics_service.domain.report import PhysicsReport, compute_report

ComputeFn = Callable[[BiomechanicsInput, Anthropometrics | None], PhysicsReport]

#: Relative (fraction-of-truth) tolerance bands — for the wide-range estimates.
RELATIVE_BANDS: dict[str, float] = {
    CLASS_LINEAR_VELOCITY: 0.15,
    CLASS_ANGULAR_VELOCITY: 0.15,
    CLASS_MOMENTUM: 0.15,
    CLASS_TORQUE: 0.20,
    CLASS_ENERGY: 0.20,
    CLASS_FORCE: 0.30,  # GRF is the highest-uncertainty estimate (§13)
}
#: Absolute tolerance bands — for bounded quantities.
ABSOLUTE_BANDS: dict[str, float] = {
    CLASS_ANGLE: 5.0,  # deg
    CLASS_DISTANCE: 3.0,  # cm
    CLASS_TIMING: 40.0,  # ms
    CLASS_RATIO: 0.15,
}

_EPS = 1e-9


@dataclass(frozen=True, slots=True)
class GoldenCase:
    """One labelled stroke: its inputs and the ground-truth quantity values."""

    name: str
    bio: BiomechanicsInput
    anthropometrics: Anthropometrics | None
    #: quantity_id -> ground-truth value. Quantities absent here are not scored.
    truth: dict[str, float]


@dataclass(frozen=True, slots=True)
class AccuracyReport:
    passed: bool
    #: quantity_class -> worst per-quantity mean absolute error in that class.
    per_class_mae: dict[str, float]
    #: quantity_class -> the band it was checked against.
    per_class_band: dict[str, float]
    #: The failing class, or 'empty_golden_set', or None if passed.
    reason: str | None
    scored: int = 0


def _band(quantity_class: str) -> float:
    if quantity_class in RELATIVE_BANDS:
        return RELATIVE_BANDS[quantity_class]
    return ABSOLUTE_BANDS.get(quantity_class, float("inf"))


def _error(quantity_id: str, computed: float, truth: float) -> tuple[str, float]:
    """(quantity_class, error expressed in the same units as its band)."""
    quantity_class = CATALOGUE[quantity_id].quantity_class
    error = abs(computed - truth)
    if quantity_class in RELATIVE_BANDS:
        return quantity_class, error / max(abs(truth), _EPS)
    return quantity_class, error


def run_accuracy_gate(
    golden: list[GoldenCase], *, compute_fn: ComputeFn = compute_report
) -> AccuracyReport:
    """Score a candidate compute against the golden set. Blocks on regression."""
    if not golden:
        return AccuracyReport(
            passed=False, per_class_mae={}, per_class_band={}, reason="empty_golden_set"
        )

    # Error accumulates PER QUANTITY (across strokes), not pooled per class: a
    # single quantity systematically off must block even though its class MAE
    # would be diluted by the well-behaved quantities beside it.
    errors: dict[str, list[float]] = defaultdict(list)
    scored = 0
    for case in golden:
        report = compute_fn(case.bio, case.anthropometrics)
        for quantity_id, truth in case.truth.items():
            quantity = report.quantities.get(quantity_id)
            if quantity is None or quantity.value is None:
                continue
            _, err = _error(quantity_id, quantity.value, truth)
            errors[quantity_id].append(err)
            scored += 1

    per_class_mae: dict[str, float] = {}
    per_class_band: dict[str, float] = {}
    reason: str | None = None
    for quantity_id, errs in errors.items():
        quantity_class = CATALOGUE[quantity_id].quantity_class
        mae = sum(errs) / len(errs)
        band = _band(quantity_class)
        per_class_band[quantity_class] = band
        per_class_mae[quantity_class] = max(per_class_mae.get(quantity_class, 0.0), mae)
        if mae > band and reason is None:
            reason = quantity_class

    return AccuracyReport(
        passed=reason is None,
        per_class_mae=per_class_mae,
        per_class_band=per_class_band,
        reason=reason,
        scored=scored,
    )


@dataclass(frozen=True, slots=True)
class SnapshotResult:
    deterministic: bool
    drifted_quantities: tuple[str, ...] = field(default_factory=tuple)


def snapshot(bio: BiomechanicsInput, anthro: Anthropometrics | None) -> dict[str, float | None]:
    """The quantity values of a report — the regression fingerprint."""
    report = compute_report(bio, anthro)
    return {qid: q.value for qid, q in report.quantities.items()}


def check_determinism(cases: list[GoldenCase]) -> SnapshotResult:
    """Recompute each case twice and assert byte-identical output (NFR-M11-02)."""
    drifted: list[str] = []
    for case in cases:
        first = snapshot(case.bio, case.anthropometrics)
        second = snapshot(case.bio, case.anthropometrics)
        drifted.extend(f"{case.name}:{qid}" for qid in first if first[qid] != second[qid])
    return SnapshotResult(deterministic=not drifted, drifted_quantities=tuple(drifted))


def check_against_snapshot(
    bio: BiomechanicsInput, anthro: Anthropometrics | None, stored: dict[str, float | None]
) -> SnapshotResult:
    """Compare a recompute against a stored snapshot; any drift blocks."""
    current = snapshot(bio, anthro)
    drifted = [qid for qid in stored if current.get(qid) != stored[qid]]
    return SnapshotResult(deterministic=not drifted, drifted_quantities=tuple(drifted))


def gate_release(model_version: str, accuracy: AccuracyReport) -> tuple[bool, str | None]:
    """The ENG-007 production gate: (ok, reason).

    A version ships only if it is registered + validated AND its accuracy
    passes. An unvalidated model is blocked even with perfect accuracy; a
    regressing model is blocked even if validated.
    """
    if not is_production_ready(model_version):
        return False, "model_not_validated"
    if not accuracy.passed:
        return False, accuracy.reason
    return True, None
