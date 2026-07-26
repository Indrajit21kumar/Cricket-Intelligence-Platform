"""The Dempster anthropometric model (M11 Step 3, §6).

Proves the segment masses/lengths scale correctly from height + body mass, that
the moments of inertia are well-formed, and — the point of §6 — that inferring
mass from height carries a larger uncertainty than a supplied mass, so the
weakness of the assumption is visible and will reach the estimate confidences.
"""

from __future__ import annotations

from physics_service.domain.anthropometry import (
    ESTIMATED_MASS_REL_UNCERTAINTY,
    PROVIDED_MASS_REL_UNCERTAINTY,
    SEGMENT_MASS_FRACTION,
    Anthropometrics,
    build_segment_model,
)


class TestMassResolution:
    def test_supplied_mass_is_used_and_firm(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        assert model.total_mass_kg == 75.0
        assert model.mass_is_estimated is False
        assert model.mass_rel_uncertainty == PROVIDED_MASS_REL_UNCERTAINTY

    def test_missing_mass_is_inferred_from_height_with_more_uncertainty(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0))
        assert model is not None
        # BMI 22.5 * 1.8^2 = 72.9 kg.
        assert round(model.total_mass_kg, 1) == 72.9
        assert model.mass_is_estimated is True
        assert model.mass_rel_uncertainty == ESTIMATED_MASS_REL_UNCERTAINTY

    def test_estimated_mass_is_less_confident_than_supplied(self) -> None:
        supplied = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        inferred = build_segment_model(Anthropometrics(height_cm=180.0))
        assert supplied is not None and inferred is not None
        assert inferred.mass_confidence < supplied.mass_confidence

    def test_no_height_no_model(self) -> None:
        assert build_segment_model(Anthropometrics(height_cm=None, body_mass_kg=75.0)) is None
        assert build_segment_model(Anthropometrics(height_cm=0.0)) is None


class TestSegments:
    def test_segment_masses_sum_to_body_mass(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        total = 0.0
        for name, seg in model.segments.items():
            # Paired segments (arms/legs) count twice.
            multiplier = (
                2.0 if name in {"upper_arm", "forearm", "hand", "thigh", "shank", "foot"} else 1.0
            )
            total += multiplier * seg.mass_kg
        assert round(total, 3) == 75.0

    def test_fractions_sum_to_whole_body(self) -> None:
        paired = {"upper_arm", "forearm", "hand", "thigh", "shank", "foot"}
        total = sum(
            (2.0 if name in paired else 1.0) * frac for name, frac in SEGMENT_MASS_FRACTION.items()
        )
        assert round(total, 4) == 1.0

    def test_segment_length_scales_from_height(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        upper_arm = model.segment("upper_arm")
        assert upper_arm is not None
        assert round(upper_arm.length_m, 4) == round(1.8 * 0.186, 4)

    def test_moment_of_inertia_is_positive_and_proximal_exceeds_cm(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        forearm = model.segment("forearm")
        assert forearm is not None
        assert forearm.moment_of_inertia_cm > 0
        # Parallel-axis: about the proximal joint it is always larger.
        assert forearm.moment_of_inertia_proximal > forearm.moment_of_inertia_cm


class TestAggregates:
    def test_arm_and_hand_masses(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        # one arm = upper 2.1 + forearm 1.2 + hand 0.45 = 3.75 kg.
        assert round(model.arm_mass_kg, 3) == 3.75
        assert round(model.both_arms_mass_kg, 3) == 7.5
        assert round(model.hands_mass_kg, 3) == 0.9

    def test_leg_mass(self) -> None:
        model = build_segment_model(Anthropometrics(height_cm=180.0, body_mass_kg=75.0))
        assert model is not None
        # thigh 7.5 + shank 3.4875 + foot 1.0875 = 12.075 kg.
        assert round(model.leg_mass_kg, 4) == 12.075
