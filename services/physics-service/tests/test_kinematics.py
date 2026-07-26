"""MEASURED kinematics PH-01..PH-05 (M11 Step 2, §5).

Proves each measured quantity is derived from the right BM input(s), labelled
MEASURED, carries the source measurement's confidence, and is honestly OMITTED
(never guessed) when its input is missing.
"""

from __future__ import annotations

from typing import Any

from physics_service.domain.biomech_input import (
    BM_COM_PATH,
    BM_GROUND_CONTACT_TIMING,
    BM_HAND_SPEED,
    BM_HIP_ROTATION,
    BM_SHOULDER_ROTATION,
    BM_X_FACTOR,
    MetricInput,
)
from physics_service.domain.kinematics import measure_kinematics
from physics_service.domain.quantities import (
    PH_01,
    PH_02,
    PH_03,
    PH_04,
    PH_05,
    PROVENANCE_MEASURED,
)


class TestBatHandSpeed:
    def test_passes_through_bm12(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio())[PH_01]
        assert q.value == 20.0
        assert q.unit == "m_per_s"
        assert q.provenance == PROVENANCE_MEASURED
        assert q.confidence == 0.8  # propagated from BM-12

    def test_confidence_is_propagated_not_invented(self, make_bio: Any) -> None:
        weak = make_bio(overrides={BM_HAND_SPEED: MetricInput(20.0, "measured", 0.3)})
        assert measure_kinematics(weak)[PH_01].confidence == 0.3

    def test_provisional_propagates(self, make_bio: Any) -> None:
        prov = make_bio(
            overrides={BM_HAND_SPEED: MetricInput(20.0, "measured", 0.5, provisional=True)}
        )
        assert measure_kinematics(prov)[PH_01].provisional is True

    def test_omitted_when_no_hand_speed(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(drop=(BM_HAND_SPEED,)))[PH_01]
        assert q.value is None
        assert q.omitted_reason == "no_hand_speed"
        assert q.confidence is None


class TestAngularVelocity:
    def test_mean_angular_velocity_over_downswing(self, make_bio: Any) -> None:
        # shoulder 90 deg / 0.1 s = 900; hip 60 / 0.1 = 600; headline = faster.
        q = measure_kinematics(make_bio())[PH_02]
        assert q.value == 900.0
        assert q.unit == "deg_per_s"
        assert q.provenance == PROVENANCE_MEASURED
        assert q.detail["shoulder_deg_per_s"] == 900.0
        assert q.detail["hip_deg_per_s"] == 600.0

    def test_omitted_without_a_timescale(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(fps=0.0))[PH_02]
        assert q.value is None
        assert q.omitted_reason == "no_downswing_duration"

    def test_omitted_without_any_rotation(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(drop=(BM_SHOULDER_ROTATION, BM_HIP_ROTATION)))[PH_02]
        assert q.value is None
        assert q.omitted_reason == "no_segment_rotation"

    def test_confidence_is_the_weakest_contributing_segment(self, make_bio: Any) -> None:
        bio = make_bio(overrides={BM_HIP_ROTATION: MetricInput(60.0, "measured", 0.4)})
        assert measure_kinematics(bio)[PH_02].confidence == 0.4


class TestBatLagSeparation:
    def test_separation_headline_with_lag_detail(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio())[PH_03]
        assert q.value == 45.0
        assert q.detail["bat_lag_deg"] == 30.0
        assert q.provenance == PROVENANCE_MEASURED

    def test_omitted_but_surfaces_lag_when_separation_missing(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(drop=(BM_X_FACTOR,)))[PH_03]
        assert q.value is None
        assert q.omitted_reason == "no_separation"
        assert q.detail["bat_lag_deg"] == 30.0


class TestCentreOfMass:
    def test_com_headline_with_head_stability_detail(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio())[PH_04]
        assert q.value == 12.0
        assert q.detail["head_stability_cm"] == 5.0
        assert q.provenance == PROVENANCE_MEASURED

    def test_omitted_when_no_com(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(drop=(BM_COM_PATH,)))[PH_04]
        assert q.value is None
        assert q.omitted_reason == "no_com_path"


class TestReactionTiming:
    def test_ground_contact_headline_with_recovery_detail(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio())[PH_05]
        assert q.value == 40.0
        assert q.detail["balance_recovery_ms"] == 300.0

    def test_absolute_timing_makes_it_provisional(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(flags=("ABSOLUTE_TIMING",)))[PH_05]
        assert q.provisional is True

    def test_omitted_when_no_timing(self, make_bio: Any) -> None:
        q = measure_kinematics(make_bio(drop=(BM_GROUND_CONTACT_TIMING,)))[PH_05]
        assert q.value is None
        assert q.omitted_reason == "no_ground_contact_timing"


class TestAllMeasured:
    def test_every_kinematic_quantity_is_labelled_measured(self, make_bio: Any) -> None:
        quantities = measure_kinematics(make_bio())
        assert {PH_01, PH_02, PH_03, PH_04, PH_05} == set(quantities)
        assert all(q.provenance == PROVENANCE_MEASURED for q in quantities.values())
