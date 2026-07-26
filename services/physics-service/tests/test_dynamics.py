"""ESTIMATED dynamics PH-06..PH-11 (M11 Step 4, §5/§13).

Proves each dynamic quantity is computed from a documented model, is labelled
ESTIMATED, always carries a confidence, and that the confidence honestly tracks
its uncertainty sources (model base, anthropometric mass, provisional). PH-10
(ball-exit) is proven to require a usable bat + tracked ball, never fabricated.
"""

from __future__ import annotations

from typing import Any

from physics_service.domain.anthropometry import Anthropometrics, build_segment_model
from physics_service.domain.biomech_input import BM_BAT_PATH_LINEARITY, BM_HAND_SPEED, MetricInput
from physics_service.domain.dynamics import estimate_dynamics
from physics_service.domain.kinematics import measure_kinematics
from physics_service.domain.quantities import (
    ESTIMATED_IDS,
    PH_06,
    PH_07,
    PH_08,
    PH_09,
    PH_10,
    PH_11,
    PROVENANCE_ESTIMATED,
)

ANTHRO = Anthropometrics(height_cm=180.0, body_mass_kg=75.0)
ANTHRO_NO_MASS = Anthropometrics(height_cm=180.0)


def _dynamics(bio: Any, anthro: Anthropometrics | None = ANTHRO) -> dict[str, Any]:
    measured = measure_kinematics(bio)
    model = build_segment_model(anthro) if anthro is not None else None
    return estimate_dynamics(bio, measured, model)


class TestProvenanceAndConfidence:
    def test_every_dynamic_is_estimated_and_carries_a_confidence(self, make_bio: Any) -> None:
        quantities = _dynamics(make_bio())
        assert set(ESTIMATED_IDS) == set(quantities)
        for q in quantities.values():
            assert q.provenance == PROVENANCE_ESTIMATED
            # The hard rule: an estimate WITH a value must carry a confidence.
            if q.value is not None:
                assert q.confidence is not None and 0.0 <= q.confidence <= 1.0


class TestMomentum:
    def test_striking_mass_times_hand_speed(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_06]
        # (bat 1.2 + hands 0.9) * 20 m/s = 42 kg.m/s.
        assert q.value == 42.0
        assert q.detail["striking_mass_kg"] == 2.1

    def test_omitted_without_anthropometrics(self, make_bio: Any) -> None:
        q = _dynamics(make_bio(), anthro=None)[PH_06]
        assert q.value is None and q.omitted_reason == "no_anthropometrics"

    def test_inferred_mass_is_less_confident_than_supplied(self, make_bio: Any) -> None:
        firm = _dynamics(make_bio(), ANTHRO)[PH_06]
        soft = _dynamics(make_bio(), ANTHRO_NO_MASS)[PH_06]
        assert soft.confidence is not None and firm.confidence is not None
        assert soft.confidence < firm.confidence


class TestTorqueAndEnergy:
    def test_torque_is_positive_with_inertia_and_accel_detail(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_07]
        assert q.value is not None and q.value > 0
        assert q.detail["swing_inertia_kg_m2"] > 0
        assert round(q.detail["angular_accel_rad_s2"], 1) == round(
            900 * 3.141592653589793 / 180 / 0.1, 1
        )

    def test_kinetic_energy_is_positive(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_08]
        assert q.value is not None and q.value > 0

    def test_omitted_without_a_timescale(self, make_bio: Any) -> None:
        # No fps -> no angular velocity -> no torque / energy.
        dyn = _dynamics(make_bio(fps=0.0))
        assert dyn[PH_07].omitted_reason == "no_angular_kinematics"
        assert dyn[PH_08].omitted_reason == "no_angular_velocity"


class TestGroundReactionForce:
    def test_force_from_weight_and_transfer(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_09]
        # 75 kg * 9.81 * (1 + 1.2*0.6) = 1265.49 N.
        assert q.value is not None and round(q.value, 1) == 1265.5
        assert round(q.detail["body_weight_multiplier"], 2) == 1.72

    def test_is_a_low_confidence_estimate(self, make_bio: Any) -> None:
        """§13: GRF is one of the highest-uncertainty estimates."""
        q = _dynamics(make_bio())[PH_09]
        ball_exit = _dynamics(make_bio())[PH_10]
        momentum = _dynamics(make_bio())[PH_06]
        assert q.confidence is not None and momentum.confidence is not None
        assert q.confidence < momentum.confidence
        assert ball_exit.confidence is not None and ball_exit.confidence < momentum.confidence


class TestSweetSpotEfficiency:
    def test_from_bat_path_linearity(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_11]
        # 0.4 + 0.6 * 0.85 = 0.91.
        assert q.value == 0.91

    def test_omitted_without_bat_path(self, make_bio: Any) -> None:
        q = _dynamics(make_bio(drop=(BM_BAT_PATH_LINEARITY,)))[PH_11]
        assert q.value is None and q.omitted_reason == "no_bat_path"

    def test_computes_without_anthropometrics(self, make_bio: Any) -> None:
        # Efficiency is mass-independent, so it survives with no body model.
        q = _dynamics(make_bio(), anthro=None)[PH_11]
        assert q.value == 0.91


class TestBallExit:
    def test_computes_when_bat_and_ball_present(self, make_bio: Any) -> None:
        q = _dynamics(make_bio())[PH_10]
        # 20*1.3 contact; collision * (1.5 * 0.6/0.76); * 0.91 efficiency ~ 28.0.
        assert q.value is not None and 27.0 < q.value < 29.0
        assert q.detail["restitution"] == 0.5

    def test_omitted_when_timing_is_absolute_no_ball(self, make_bio: Any) -> None:
        q = _dynamics(make_bio(flags=("ABSOLUTE_TIMING",)))[PH_10]
        assert q.value is None and q.omitted_reason == "no_tracked_ball_contact"

    def test_omitted_when_bat_lost_through_impact(self, make_bio: Any) -> None:
        lost = make_bio(
            overrides={BM_HAND_SPEED: MetricInput(20.0, "measured", 0.4, provisional=True)}
        )
        q = _dynamics(lost)[PH_10]
        assert q.value is None and q.omitted_reason == "no_usable_bat_at_contact"

    def test_omitted_when_no_bat_speed(self, make_bio: Any) -> None:
        q = _dynamics(make_bio(drop=(BM_HAND_SPEED,)))[PH_10]
        assert q.value is None and q.omitted_reason == "no_usable_bat_at_contact"


class TestProvisionalPropagation:
    def test_provisional_report_softens_and_flags_estimates(self, make_bio: Any) -> None:
        firm = _dynamics(make_bio())[PH_06]
        prov = _dynamics(make_bio(provisional=True))[PH_06]
        assert prov.provisional is True
        assert prov.confidence is not None and firm.confidence is not None
        assert prov.confidence < firm.confidence
