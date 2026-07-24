"""Bat angle + swing plane in the CIP frame (M07 Step 5, AC-M07-01/04)."""

from __future__ import annotations

import math

import pytest

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    PROVENANCE_DERIVED,
    BatFrame,
    BatPart,
)
from bat_service.domain.geometry import (
    MIN_PLANE_FRAMES,
    bat_angle,
    bat_angles,
    swing_plane,
)


def _frame(
    index: int,
    *,
    shoulder: tuple[float, float] = (0.0, 0.0),
    tip: tuple[float, float] = (0.0, 0.3),
    confidence: float = 0.9,
    detected: bool = True,
) -> BatFrame:
    if not detected:
        return BatFrame(frame_index=index, detected=False)
    parts = (
        BatPart(part=HANDLE_BOTTOM, x=shoulder[0], y=shoulder[1], confidence=confidence),
        BatPart(part=BLADE_TIP, x=tip[0], y=tip[1], confidence=confidence),
    )
    return BatFrame(frame_index=index, detected=True, parts=parts, confidence=confidence)


class TestBatAngle:
    def test_bat_pointing_up_is_zero_degrees(self) -> None:
        """CIP frame is Y-up, so a raised bat reads 0."""
        angle = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.0, 0.3)))
        assert angle is not None
        assert angle.degrees == pytest.approx(0.0)

    def test_bat_pointing_down_is_180_degrees(self) -> None:
        angle = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.0, -0.3)))
        assert angle is not None
        assert abs(angle.degrees) == pytest.approx(180.0)

    def test_blade_along_positive_x_is_plus_90(self) -> None:
        angle = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.3, 0.0)))
        assert angle is not None
        assert angle.degrees == pytest.approx(90.0)

    def test_blade_along_negative_x_is_minus_90(self) -> None:
        angle = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(-0.3, 0.0)))
        assert angle is not None
        assert angle.degrees == pytest.approx(-90.0)

    def test_forty_five_degrees(self) -> None:
        angle = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.2, 0.2)))
        assert angle is not None
        assert angle.degrees == pytest.approx(45.0)

    def test_angle_is_scale_invariant(self) -> None:
        """Same geometry, longer blade: same angle."""
        short = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.1, 0.1)))
        long = bat_angle(_frame(0, shoulder=(0.0, 0.0), tip=(0.4, 0.4)))
        assert short is not None and long is not None
        assert short.degrees == pytest.approx(long.degrees)


class TestAngleHonesty:
    def test_angle_is_labelled_derived(self) -> None:
        """AC-M07-04: computed from two points, so never 'measured'."""
        angle = bat_angle(_frame(0))
        assert angle is not None
        assert angle.provenance == PROVENANCE_DERIVED

    def test_confidence_is_the_weaker_endpoint(self) -> None:
        parts = (
            BatPart(part=HANDLE_BOTTOM, x=0.0, y=0.0, confidence=0.9),
            BatPart(part=BLADE_TIP, x=0.0, y=0.3, confidence=0.4),
        )
        frame = BatFrame(frame_index=0, detected=True, parts=parts, confidence=0.4)
        angle = bat_angle(frame)
        assert angle is not None
        assert angle.confidence == pytest.approx(0.4)

    def test_missing_blade_tip_yields_no_angle(self) -> None:
        parts = (BatPart(part=HANDLE_BOTTOM, x=0.0, y=0.0, confidence=0.9),)
        frame = BatFrame(frame_index=0, detected=True, parts=parts, confidence=0.9)
        assert bat_angle(frame) is None

    def test_zero_length_blade_yields_no_angle(self) -> None:
        """A degenerate blade has no direction; 0 degrees would be a lie."""
        assert bat_angle(_frame(0, shoulder=(0.1, 0.1), tip=(0.1, 0.1))) is None

    def test_undetected_frames_are_skipped(self) -> None:
        frames = (_frame(0), _frame(1, detected=False), _frame(2))
        assert [a.frame_index for a in bat_angles(frames)] == [0, 2]


class TestSwingPlane:
    def test_vertical_swing_is_fitted(self) -> None:
        """A straight-bat swing is near-vertical — the case OLS would break on."""
        frames = tuple(_frame(i, shoulder=(0.0, 0.0), tip=(0.0, -0.3 + 0.1 * i)) for i in range(8))
        plane = swing_plane(frames)
        assert plane is not None
        assert abs(plane.inclination_degrees) == pytest.approx(0.0, abs=1e-6)
        assert plane.linearity > 0.99

    def test_diagonal_swing_reports_its_inclination(self) -> None:
        frames = tuple(_frame(i, shoulder=(0.0, 0.0), tip=(0.05 * i, 0.05 * i)) for i in range(8))
        plane = swing_plane(frames)
        assert plane is not None
        assert plane.inclination_degrees == pytest.approx(45.0)

    def test_plane_orientation_is_stable(self) -> None:
        """The same arc traversed either way must not report opposite planes."""
        forward = tuple(_frame(i, tip=(0.04 * i, 0.05 * i)) for i in range(8))
        backward = tuple(_frame(i, tip=(0.04 * (7 - i), 0.05 * (7 - i))) for i in range(8))
        a, b = swing_plane(forward), swing_plane(backward)
        assert a is not None and b is not None
        assert a.inclination_degrees == pytest.approx(b.inclination_degrees)

    def test_scattered_points_lower_linearity_and_confidence(self) -> None:
        tidy = tuple(_frame(i, tip=(0.0, -0.3 + 0.1 * i)) for i in range(8))
        noisy = tuple(_frame(i, tip=(0.08 * math.sin(i * 2.0), -0.3 + 0.1 * i)) for i in range(8))
        clean_plane, noisy_plane = swing_plane(tidy), swing_plane(noisy)
        assert clean_plane is not None and noisy_plane is not None
        assert noisy_plane.linearity < clean_plane.linearity
        assert noisy_plane.confidence < clean_plane.confidence


class TestPlaneRefusals:
    def test_too_few_frames_yields_no_plane(self) -> None:
        """Two points define a line, not evidence of a swing plane."""
        frames = tuple(_frame(i, tip=(0.0, 0.1 * i)) for i in range(MIN_PLANE_FRAMES - 1))
        assert swing_plane(frames) is None

    def test_a_stationary_bat_yields_no_plane(self) -> None:
        """Below the spread floor the fit direction is noise, not geometry."""
        frames = tuple(_frame(i, tip=(0.001 * i, 0.001 * i)) for i in range(10))
        assert swing_plane(frames) is None

    def test_undetected_frames_do_not_count_toward_the_minimum(self) -> None:
        frames = (
            _frame(0, tip=(0.0, 0.0)),
            _frame(1, detected=False),
            _frame(2, detected=False),
            _frame(3, tip=(0.0, 0.3)),
        )
        assert swing_plane(frames) is None

    def test_plane_is_labelled_derived(self) -> None:
        frames = tuple(_frame(i, tip=(0.0, -0.3 + 0.1 * i)) for i in range(8))
        plane = swing_plane(frames)
        assert plane is not None
        assert plane.provenance == PROVENANCE_DERIVED
