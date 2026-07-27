"""Accuracy gate + determinism + release gating (M11 Step 8, AC-M11-07/08, ENG-007).

The gate's job is to BLOCK. These tests prove: the reference compute passes its
own golden set; a change that drifts a quantity beyond its class band is blocked;
sub-band error still passes; the compute is deterministic; and an unvalidated or
regressing model is blocked from production.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.biomech_input import BM_HAND_SPEED, MetricInput
from physics_service.domain.models import ACTIVE_MODEL_VERSION
from physics_service.domain.quantities import (
    CLASS_FORCE,
    CLASS_MOMENTUM,
    CLASS_RATIO,
    PH_06,
    PH_09,
    PH_11,
    PhysicsQuantity,
)
from physics_service.domain.report import PhysicsReport, compute_report
from physics_service.domain.validation import (
    GoldenCase,
    check_against_snapshot,
    check_determinism,
    gate_release,
    run_accuracy_gate,
    snapshot,
)

ANTHRO = Anthropometrics(height_cm=180.0, body_mass_kg=75.0)


def _golden(make_bio: Any) -> list[GoldenCase]:
    """Truth = the reference compute's own values (a snapshot golden)."""
    cases: list[GoldenCase] = []
    for i in range(3):
        bio = make_bio(
            correlation_id=f"golden-{i}",
            overrides={BM_HAND_SPEED: MetricInput(18.0 + i, "measured", 0.8)},
        )
        report = compute_report(bio, ANTHRO)
        truth = {qid: q.value for qid, q in report.quantities.items() if q.value is not None}
        cases.append(
            GoldenCase(name=bio.correlation_id, bio=bio, anthropometrics=ANTHRO, truth=truth)
        )
    return cases


def _drift(quantity_id: str, *, factor: float | None = None, delta: float | None = None) -> Any:
    def fn(bio: Any, anthro: Anthropometrics | None) -> PhysicsReport:
        report = compute_report(bio, anthro)
        quantities = dict(report.quantities)
        q: PhysicsQuantity = quantities[quantity_id]
        base = q.value or 0.0
        new_value = base * factor if factor is not None else base + (delta or 0.0)
        quantities[quantity_id] = replace(q, value=new_value)
        return replace(report, quantities=quantities)

    return fn


class TestAccuracyGate:
    def test_the_reference_compute_passes(self, make_bio: Any) -> None:
        report = run_accuracy_gate(_golden(make_bio))
        assert report.passed is True, report.reason
        assert report.scored > 0

    def test_a_force_drift_beyond_30pct_is_blocked(self, make_bio: Any) -> None:
        result = run_accuracy_gate(_golden(make_bio), compute_fn=_drift(PH_09, factor=1.5))
        assert result.passed is False
        assert result.reason == CLASS_FORCE

    def test_a_momentum_drift_beyond_15pct_is_blocked(self, make_bio: Any) -> None:
        result = run_accuracy_gate(_golden(make_bio), compute_fn=_drift(PH_06, factor=1.3))
        assert result.passed is False
        assert result.reason == CLASS_MOMENTUM

    def test_a_ratio_drift_beyond_the_band_is_blocked(self, make_bio: Any) -> None:
        result = run_accuracy_gate(_golden(make_bio), compute_fn=_drift(PH_11, delta=0.3))
        assert result.passed is False
        assert result.reason == CLASS_RATIO

    def test_a_small_drift_within_the_band_still_passes(self, make_bio: Any) -> None:
        result = run_accuracy_gate(_golden(make_bio), compute_fn=_drift(PH_06, factor=1.05))
        assert result.passed is True

    def test_empty_golden_set_is_not_a_pass(self) -> None:
        report = run_accuracy_gate([])
        assert report.passed is False
        assert report.reason == "empty_golden_set"


class TestDeterminism:
    def test_the_compute_is_deterministic(self, make_bio: Any) -> None:
        """AC-M11-08 / NFR-M11-02."""
        result = check_determinism(_golden(make_bio))
        assert result.deterministic is True
        assert result.drifted_quantities == ()

    def test_a_drifted_snapshot_is_caught(self, make_bio: Any) -> None:
        bio = make_bio()
        stored = snapshot(bio, ANTHRO)
        stored[PH_06] = (stored[PH_06] or 0.0) + 1.0
        result = check_against_snapshot(bio, ANTHRO, stored)
        assert result.deterministic is False
        assert PH_06 in result.drifted_quantities


class TestReleaseGate:
    def test_validated_model_with_passing_accuracy_ships(self, make_bio: Any) -> None:
        accuracy = run_accuracy_gate(_golden(make_bio))
        ok, reason = gate_release(ACTIVE_MODEL_VERSION, accuracy)
        assert ok is True and reason is None

    def test_unvalidated_model_is_blocked_even_with_perfect_accuracy(self, make_bio: Any) -> None:
        accuracy = run_accuracy_gate(_golden(make_bio))
        assert accuracy.passed is True
        ok, reason = gate_release("phys-est-9.9.9-unregistered", accuracy)
        assert ok is False and reason == "model_not_validated"

    def test_regressing_model_is_blocked_even_if_validated(self, make_bio: Any) -> None:
        accuracy = run_accuracy_gate(_golden(make_bio), compute_fn=_drift(PH_09, factor=1.5))
        ok, reason = gate_release(ACTIVE_MODEL_VERSION, accuracy)
        assert ok is False and reason == CLASS_FORCE
