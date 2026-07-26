"""Kinetic-chain energy transfer + loss points (M11 Step 5, §5, AC-M11-04).

Proves the chain builds the proximal-to-distal speed sequence, recognises a
well-sequenced swing, and detects the leaks — the flagship hip->shoulder leak
and a chain that fails to start from the ground — all labelled ESTIMATED.
"""

from __future__ import annotations

from typing import Any

from physics_service.domain.anthropometry import Anthropometrics, build_segment_model
from physics_service.domain.biomech_input import (
    BM_SHOULDER_ROTATION,
    BM_WEIGHT_TRANSFER,
    MetricInput,
)
from physics_service.domain.kinematics import measure_kinematics
from physics_service.domain.kinetic_chain import (
    LINK_BAT,
    LINK_HANDS,
    LINK_PELVIS,
    LINK_TRUNK,
    SEVERITY_MAJOR,
    build_kinetic_chain,
)
from physics_service.domain.quantities import PROVENANCE_ESTIMATED, PROVENANCE_MEASURED

ANTHRO = Anthropometrics(height_cm=180.0, body_mass_kg=75.0)


def _chain(bio: Any, anthro: Anthropometrics | None = ANTHRO) -> Any:
    measured = measure_kinematics(bio)
    model = build_segment_model(anthro) if anthro is not None else None
    return build_kinetic_chain(bio, measured, model)


def _speeds(chain: Any) -> dict[str, float]:
    return {link.name: link.speed_mps for link in chain.links if link.speed_mps is not None}


class TestWellSequencedSwing:
    def test_speed_amplifies_down_the_chain(self, make_bio: Any) -> None:
        chain = _chain(make_bio())
        speeds = _speeds(chain)
        assert speeds[LINK_PELVIS] < speeds[LINK_TRUNK] < speeds[LINK_HANDS] < speeds[LINK_BAT]

    def test_a_clean_swing_has_no_loss_points(self, make_bio: Any) -> None:
        chain = _chain(make_bio())
        assert chain.loss_points == ()
        assert chain.sequence_ok is True

    def test_link_speeds_match_the_model(self, make_bio: Any) -> None:
        speeds = _speeds(_chain(make_bio()))
        # pelvis: 600 deg/s * (0.10*1.8) ; trunk: 900 deg/s * (0.11*1.8).
        assert round(speeds[LINK_PELVIS], 3) == 1.885
        assert round(speeds[LINK_TRUNK], 3) == 3.11
        assert speeds[LINK_HANDS] == 20.0
        assert speeds[LINK_BAT] == 26.0

    def test_engagement_from_weight_transfer(self, make_bio: Any) -> None:
        assert _chain(make_bio()).lower_body_engagement == 0.6


class TestProvenance:
    def test_chain_is_estimated_but_hands_link_is_measured(self, make_bio: Any) -> None:
        chain = _chain(make_bio())
        assert chain.provenance == PROVENANCE_ESTIMATED
        hands = next(link for link in chain.links if link.name == LINK_HANDS)
        assert hands.provenance == PROVENANCE_MEASURED

    def test_confidence_is_present(self, make_bio: Any) -> None:
        assert _chain(make_bio()).confidence is not None


class TestLeakDetection:
    def test_hip_shoulder_leak_is_flagged(self, make_bio: Any) -> None:
        """The trunk rotates far less than the hips: the classic X-factor leak."""
        stiff_trunk = make_bio(overrides={BM_SHOULDER_ROTATION: MetricInput(10.0, "measured", 0.9)})
        chain = _chain(stiff_trunk)
        leak = next(lp for lp in chain.loss_points if lp.from_link == LINK_PELVIS)
        assert leak.to_link == LINK_TRUNK
        assert leak.severity == SEVERITY_MAJOR
        assert chain.sequence_ok is False

    def test_weak_foundation_is_a_loss_point(self, make_bio: Any) -> None:
        weak = make_bio(overrides={BM_WEIGHT_TRANSFER: MetricInput(0.2, "estimated", 0.5)})
        chain = _chain(weak)
        foundation = next(lp for lp in chain.loss_points if lp.from_link == "feet")
        assert foundation.severity == SEVERITY_MAJOR
        assert chain.sequence_ok is False


class TestDegraded:
    def test_without_anthropometrics_the_upper_links_still_analyse(self, make_bio: Any) -> None:
        # No height -> no pelvis/trunk speed, but the measured hands + bat remain,
        # and their transfer is still checked.
        chain = _chain(make_bio(), anthro=None)
        speeds = _speeds(chain)
        assert LINK_PELVIS not in speeds and LINK_TRUNK not in speeds
        assert speeds[LINK_HANDS] == 20.0 and speeds[LINK_BAT] == 26.0
        assert chain.sequence_ok is True

    def test_payload_round_trips_the_structure(self, make_bio: Any) -> None:
        payload = _chain(make_bio()).to_payload()
        assert payload["provenance"] == "estimated"
        assert payload["sequence_ok"] is True
        assert {link["name"] for link in payload["links"]} == {
            LINK_PELVIS,
            LINK_TRUNK,
            LINK_HANDS,
            LINK_BAT,
        }

    def test_provisional_report_softens_and_flags_the_chain(self, make_bio: Any) -> None:
        firm = _chain(make_bio())
        prov = _chain(make_bio(provisional=True))
        assert "PROVISIONAL" in prov.flags
        assert prov.confidence is not None and firm.confidence is not None
        assert prov.confidence < firm.confidence
