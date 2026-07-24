"""Unit tests for part localisation + sweet-spot derivation (M07 Step 3).

AC-M07-04 in particular: the sweet spot must be labelled derived and carry
lower confidence than the points it was computed from.
"""

from __future__ import annotations

import pytest

from bat_service.domain.bat import (
    BLADE_TIP,
    DETECTED_PARTS,
    HANDLE_BOTTOM,
    HANDLE_TOP,
    PROVENANCE_DERIVED,
    PROVENANCE_MEASURED,
    SWEET_SPOT,
    BatDetection,
    BatPart,
)
from bat_service.domain.detector import FakeBatDetector
from bat_service.domain.parts import (
    SWEET_SPOT_BLADE_FRACTION,
    derive_sweet_spot,
    detection_confidence,
    with_derived_parts,
)


def _detection(
    *,
    shoulder: tuple[float, float] = (100.0, 100.0),
    tip: tuple[float, float] = (100.0, 200.0),
    confidence: float = 0.9,
    include_shoulder: bool = True,
    include_tip: bool = True,
) -> BatDetection:
    parts = [BatPart(part=HANDLE_TOP, x=100.0, y=60.0, confidence=confidence)]
    if include_shoulder:
        parts.append(
            BatPart(part=HANDLE_BOTTOM, x=shoulder[0], y=shoulder[1], confidence=confidence)
        )
    if include_tip:
        parts.append(BatPart(part=BLADE_TIP, x=tip[0], y=tip[1], confidence=confidence))
    return BatDetection(parts=tuple(parts), score=confidence)


class TestSweetSpotGeometry:
    def test_sits_the_expected_fraction_down_the_blade(self) -> None:
        sweet = derive_sweet_spot(_detection(shoulder=(100.0, 100.0), tip=(100.0, 200.0)))
        assert sweet is not None
        # Blade runs 100 -> 200 in y; the sweet spot is 70% along it.
        assert sweet.y == pytest.approx(100.0 + 100.0 * SWEET_SPOT_BLADE_FRACTION)
        assert sweet.x == pytest.approx(100.0)

    def test_follows_an_angled_blade(self) -> None:
        sweet = derive_sweet_spot(_detection(shoulder=(0.0, 0.0), tip=(100.0, 100.0)))
        assert sweet is not None
        assert sweet.x == pytest.approx(70.0)
        assert sweet.y == pytest.approx(70.0)


class TestDerivedLabelling:
    def test_sweet_spot_is_labelled_derived(self) -> None:
        """AC-M07-04: a modelled point must never claim to be measured."""
        sweet = derive_sweet_spot(_detection())
        assert sweet is not None
        assert sweet.part == SWEET_SPOT
        assert sweet.provenance == PROVENANCE_DERIVED

    def test_sweet_spot_confidence_is_below_its_inputs(self) -> None:
        sweet = derive_sweet_spot(_detection(confidence=0.9))
        assert sweet is not None
        assert sweet.confidence < 0.9

    def test_confidence_is_bounded_by_the_weaker_input(self) -> None:
        """A shaky blade tip must drag the derived point down with it."""
        parts = (
            BatPart(part=HANDLE_BOTTOM, x=0.0, y=0.0, confidence=0.9),
            BatPart(part=BLADE_TIP, x=0.0, y=100.0, confidence=0.3),
        )
        sweet = derive_sweet_spot(BatDetection(parts=parts, score=0.9))
        assert sweet is not None
        assert sweet.confidence < 0.3


class TestPartialBats:
    def test_missing_blade_tip_yields_no_sweet_spot(self) -> None:
        """Better absent than invented."""
        assert derive_sweet_spot(_detection(include_tip=False)) is None

    def test_missing_shoulder_yields_no_sweet_spot(self) -> None:
        assert derive_sweet_spot(_detection(include_shoulder=False)) is None

    def test_with_derived_parts_passes_partial_detections_through(self) -> None:
        detection = _detection(include_tip=False)
        assert with_derived_parts(detection) is detection


class TestAssembly:
    def test_detected_parts_come_first_then_derived(self) -> None:
        enriched = with_derived_parts(_detection())
        names = [p.part for p in enriched.parts]
        assert names == [*DETECTED_PARTS, SWEET_SPOT]
        assert all(
            p.provenance == PROVENANCE_MEASURED for p in enriched.parts if p.part in DETECTED_PARTS
        )

    def test_works_on_real_detector_output(self) -> None:
        frames = FakeBatDetector().detect(frame_count=5, width=1920, height=1080)
        enriched = with_derived_parts(frames[0].bats[0])
        assert enriched.part(SWEET_SPOT) is not None


class TestDetectionConfidence:
    def test_uses_the_weakest_measured_part(self) -> None:
        """A confident handle must not mask a blade tip that was barely found."""
        parts = (
            BatPart(part=HANDLE_TOP, x=0.0, y=0.0, confidence=0.95),
            BatPart(part=HANDLE_BOTTOM, x=0.0, y=10.0, confidence=0.95),
            BatPart(part=BLADE_TIP, x=0.0, y=100.0, confidence=0.20),
        )
        assert detection_confidence(BatDetection(parts=parts, score=0.9)) == pytest.approx(0.20)

    def test_derived_parts_do_not_drag_the_score_down(self) -> None:
        """The derived penalty is reported on the point, not counted twice."""
        detection = _detection(confidence=0.8)
        assert detection_confidence(with_derived_parts(detection)) == pytest.approx(0.8)

    def test_no_measured_parts_is_zero(self) -> None:
        assert detection_confidence(BatDetection(parts=(), score=0.5)) == 0.0
