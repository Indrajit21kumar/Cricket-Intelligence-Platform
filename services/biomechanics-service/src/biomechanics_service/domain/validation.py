"""Accuracy gate + snapshot regression (M10 Step 8, ENG-007, §10, §15).

Two release gates, both blocking:

**Accuracy vs mocap (REQ-BIO-031/036, AC-M10-06).** A pipeline change MUST NOT
ship if it regresses mean absolute error beyond the Section 10 tolerance bands,
and the bands differ BY METRIC CLASS — an angular metric is allowed 5 degrees,
a timing metric 2 frames, a linear metric 3 cm (only where spatial confidence
is high), a velocity metric 10%. So error is accumulated per class and each
class's MAE is checked against its own band. A single loose band would either
wave through an angular regression or reject an acceptable velocity one; the
per-class split is the point.

**Snapshot regression (REQ-BIO-037, NFR-M10-03, AC-M10-08).** M10 is pure
deterministic arithmetic, so identical input must give byte-identical output.
The regression check recomputes a reference stroke and asserts the metrics are
unchanged — any drift at all is a regression, because there is no legitimate
source of nondeterminism to excuse it.

The mocap golden corpus (>=200 validated strokes) is a data workstream that does
not exist yet. The gate is built and tested against labelled fixture strokes and
wired into CI, so it starts blocking the moment real mocap data lands.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field

from biomechanics_service.domain.builder import RawStroke
from biomechanics_service.domain.catalogue import (
    CATALOGUE,
    CLASS_ANGULAR,
    CLASS_LINEAR,
    CLASS_RATIO,
    CLASS_TIMING,
    CLASS_VELOCITY,
)
from biomechanics_service.domain.report import BiomechanicsReport, compute_report
from biomechanics_service.domain.stroke import SPATIAL_HIGH

#: Absolute tolerance per metric class (Section 10). Timing is 2 frames,
#: converted to the metric's ms unit with the stroke's fps. Velocity is a
#: RELATIVE tolerance (10%). Ratio has no Section 10 band; a modest default.
ANGULAR_TOLERANCE_DEG = 5.0
LINEAR_TOLERANCE_CM = 3.0
VELOCITY_TOLERANCE_FRACTION = 0.10
TIMING_TOLERANCE_FRAMES = 2.0
RATIO_TOLERANCE = 0.10

ComputeFn = Callable[[RawStroke], BiomechanicsReport]


@dataclass(frozen=True, slots=True)
class GoldenStroke:
    """One labelled stroke: its inputs and the mocap-truth metric values."""

    name: str
    raw: RawStroke
    #: metric_id -> ground-truth value. Metrics absent here are not scored.
    truth: dict[str, float]


@dataclass(frozen=True, slots=True)
class AccuracyReport:
    passed: bool
    #: metric_class -> mean absolute error across the golden set.
    per_class_mae: dict[str, float]
    #: metric_class -> the band it was checked against.
    per_class_band: dict[str, float]
    #: The class that failed, or 'empty_golden_set', or None if passed.
    reason: str | None
    scored: int = 0


def _within(metric_id: str, computed: float, truth: float, *, fps: float) -> tuple[str, float]:
    """Return (metric_class, error-normalised-to-its-band-units) for one metric."""
    metric_class = CATALOGUE[metric_id].metric_class
    error = abs(computed - truth)
    if metric_class == CLASS_VELOCITY:
        # Relative error, expressed as a fraction so it compares to the band.
        denom = abs(truth) if truth != 0 else 1.0
        return metric_class, error / denom
    return metric_class, error


_BANDS = {
    CLASS_ANGULAR: ANGULAR_TOLERANCE_DEG,
    CLASS_LINEAR: LINEAR_TOLERANCE_CM,
    CLASS_VELOCITY: VELOCITY_TOLERANCE_FRACTION,
    CLASS_RATIO: RATIO_TOLERANCE,
}


def _timing_band(fps: float) -> float:
    return TIMING_TOLERANCE_FRAMES / fps * 1000.0 if fps > 0 else float("inf")


def run_accuracy_gate(
    golden: list[GoldenStroke],
    *,
    compute_fn: ComputeFn = compute_report,
) -> AccuracyReport:
    """Score a candidate compute against the golden set. Blocks on regression."""
    if not golden:
        return AccuracyReport(
            passed=False,
            per_class_mae={},
            per_class_band={},
            reason="empty_golden_set",
        )

    # Error accumulates PER METRIC (across strokes), not pooled per class: a
    # single metric that is systematically 10 deg wrong must block, even though
    # its class MAE would be diluted by the well-behaved metrics beside it.
    errors: dict[str, list[float]] = defaultdict(list)
    scored = 0
    for sample in golden:
        report = compute_fn(sample.raw)
        fps = sample.raw.calibration.fps
        high_spatial = sample.raw.calibration.spatial_confidence == SPATIAL_HIGH
        for metric_id, truth in sample.truth.items():
            mv = report.metrics.get(metric_id)
            if mv is None or mv.value is None:
                continue
            metric_class = CATALOGUE[metric_id].metric_class
            # Linear metrics are only accuracy-gated at high spatial confidence
            # (Section 10) — a depth-degraded linear value is not held to 3 cm.
            if metric_class == CLASS_LINEAR and not high_spatial:
                continue
            _, err = _within(metric_id, mv.value, truth, fps=fps)
            errors[metric_id].append(err)
            scored += 1

    per_class_mae: dict[str, float] = {}
    per_class_band: dict[str, float] = {}
    reason: str | None = None
    # A single fps for the timing band; the golden set shares a capture rate.
    fps = golden[0].raw.calibration.fps
    for metric_id, errs in errors.items():
        metric_class = CATALOGUE[metric_id].metric_class
        mae = sum(errs) / len(errs)
        band = _timing_band(fps) if metric_class == CLASS_TIMING else _BANDS[metric_class]
        per_class_band[metric_class] = band
        # Report the WORST metric MAE per class, so the number shows how close
        # the class came to its band.
        per_class_mae[metric_class] = max(per_class_mae.get(metric_class, 0.0), mae)
        if mae > band and reason is None:
            reason = metric_class

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
    drifted_metrics: tuple[str, ...] = field(default_factory=tuple)


def snapshot(raw: RawStroke) -> dict[str, float | None]:
    """The metric values of a stroke's report — the regression fingerprint."""
    report = compute_report(raw)
    return {metric_id: mv.value for metric_id, mv in report.metrics.items()}


def check_determinism(strokes: list[RawStroke]) -> SnapshotResult:
    """Recompute each stroke and assert byte-identical output (NFR-M10-03).

    Any drift is a regression: pure arithmetic has no legitimate source of
    nondeterminism to excuse a difference.
    """
    drifted: list[str] = []
    for raw in strokes:
        first = snapshot(raw)
        second = snapshot(raw)
        for metric_id in first:
            if first[metric_id] != second[metric_id]:
                drifted.append(f"{raw.correlation_id}:{metric_id}")
    return SnapshotResult(deterministic=not drifted, drifted_metrics=tuple(drifted))


def check_against_snapshot(raw: RawStroke, stored: dict[str, float | None]) -> SnapshotResult:
    """Compare a recompute against a stored snapshot; any drift blocks."""
    current = snapshot(raw)
    drifted = [metric_id for metric_id in stored if current.get(metric_id) != stored[metric_id]]
    return SnapshotResult(deterministic=not drifted, drifted_metrics=tuple(drifted))
