"""Unit tests for the quality gate (M05 Step 6, FR-M05-06, AC-M05-02).

Pure logic over the measurement envelope + angle result. Typical (good clip
admitted), each failure check, soft-flag zones, and the admit rule.
"""

from __future__ import annotations

import dataclasses

import pytest

from video_service.domain.angle import AngleResult
from video_service.domain.processor import ClipMeasurements, _good_clip
from video_service.domain.quality_gate import run_quality_gate


def _angle(supported: bool = True) -> AngleResult:
    return AngleResult(
        camera_angle="side_on" if supported else "square",
        supported=supported,
        confidence=0.9,
        recommendation=None if supported else "Move side-on.",
    )


def _measure(**overrides: object) -> ClipMeasurements:
    return dataclasses.replace(_good_clip(), **overrides)  # type: ignore[arg-type]


def _unassessed_angle() -> AngleResult:
    """What the gate sees when no angle classifier ran at all."""
    return AngleResult(
        camera_angle="other",
        supported=False,
        confidence=0.0,
        recommendation="Camera angle isn't analysed yet.",
        assessed=False,
    )


def _codes(measurements: ClipMeasurements, supported: bool = True) -> set[str]:
    return {
        f.code for f in run_quality_gate(measurements=measurements, angle=_angle(supported)).flags
    }


class TestGoodClip:
    def test_clean_clip_admitted_no_flags(self) -> None:
        result = run_quality_gate(measurements=_good_clip(), angle=_angle())
        assert result.admitted is True
        assert result.flags == ()


class TestHardFails:
    def test_low_resolution_fails(self) -> None:
        result = run_quality_gate(measurements=_measure(width=640, height=480), angle=_angle())
        assert result.admitted is False
        assert "resolution_too_low" in result.fail_reasons

    def test_low_fps_fails(self) -> None:
        result = run_quality_gate(measurements=_measure(fps=15.0), angle=_angle())
        assert result.admitted is False
        assert "frame_rate_too_low" in result.fail_reasons

    def test_excessive_blur_fails(self) -> None:
        assert "excessive_blur" in {
            f.code
            for f in run_quality_gate(measurements=_measure(blur_score=0.8), angle=_angle()).flags
            if f.severity == "fail"
        }

    def test_batter_not_in_frame_fails(self) -> None:
        result = run_quality_gate(measurements=_measure(batter_in_frame=0.5), angle=_angle())
        assert result.admitted is False
        assert "batter_not_in_frame" in result.fail_reasons

    def test_underexposed_and_overexposed_fail(self) -> None:
        assert "underexposed" in {
            f.code
            for f in run_quality_gate(measurements=_measure(exposure=0.05), angle=_angle()).flags
        }
        assert "overexposed" in {
            f.code
            for f in run_quality_gate(measurements=_measure(exposure=0.95), angle=_angle()).flags
        }

    def test_duration_out_of_range_fails(self) -> None:
        assert (
            run_quality_gate(measurements=_measure(duration_s=0.5), angle=_angle()).admitted
            is False
        )
        assert (
            run_quality_gate(measurements=_measure(duration_s=99.0), angle=_angle()).admitted
            is False
        )


class TestOrientation:
    """Resolution is judged on pixels, not on which edge is wider.

    Phones default to portrait, and 1080x1920 carries 2.25x the pixels of
    1280x720 — rejecting it as "too low" was wrong and unexplainable to the
    person who filmed it.
    """

    def test_portrait_1080x1920_is_admitted(self) -> None:
        result = run_quality_gate(measurements=_measure(width=1080, height=1920), angle=_angle())
        assert result.admitted is True
        assert "resolution_too_low" not in result.fail_reasons

    def test_portrait_is_soft_flagged_to_prefer_landscape(self) -> None:
        assert "portrait_orientation" in _codes(_measure(width=1080, height=1920))

    def test_landscape_is_not_orientation_flagged(self) -> None:
        assert "portrait_orientation" not in _codes(_measure(width=1920, height=1080))

    @pytest.mark.parametrize(("w", "h"), [(848, 478), (478, 848), (640, 480), (1280, 600)])
    def test_genuinely_small_clips_still_fail_either_orientation(self, w: int, h: int) -> None:
        result = run_quality_gate(measurements=_measure(width=w, height=h), angle=_angle())
        assert result.admitted is False
        assert "resolution_too_low" in result.fail_reasons

    def test_low_resolution_message_mentions_messaging_app_compression(self) -> None:
        flags = run_quality_gate(measurements=_measure(width=848, height=478), angle=_angle()).flags
        message = next(f.message for f in flags if f.code == "resolution_too_low")
        assert "WhatsApp" in message


class TestDurationGuidance:
    def test_too_long_clip_is_told_to_trim(self) -> None:
        flags = run_quality_gate(measurements=_measure(duration_s=161.0), angle=_angle()).flags
        message = next(f.message for f in flags if f.code == "duration_out_of_range")
        assert "trim" in message.lower()

    def test_too_short_clip_is_told_to_record_longer(self) -> None:
        flags = run_quality_gate(measurements=_measure(duration_s=1.2), angle=_angle()).flags
        message = next(f.message for f in flags if f.code == "duration_out_of_range")
        assert "too short" in message.lower()


class TestUnassessedAngle:
    """An angle nothing measured is a capability gap, not a filming fault."""

    def test_unassessed_angle_uses_its_own_code(self) -> None:
        unassessed = _unassessed_angle()
        result = run_quality_gate(measurements=_good_clip(), angle=unassessed)
        codes = {f.code for f in result.flags}
        assert "camera_angle_not_assessed" in codes
        assert "unsupported_camera_angle" not in codes  # don't blame the operator

    def test_unassessed_angle_still_admits(self) -> None:
        unassessed = _unassessed_angle()
        assert run_quality_gate(measurements=_good_clip(), angle=unassessed).admitted is True


class TestSoftFlags:
    def test_marginal_fps_is_soft_flag_still_admitted(self) -> None:
        result = run_quality_gate(measurements=_measure(fps=25.0), angle=_angle())
        assert result.admitted is True  # 24 <= 25 < 30 -> flag, not fail
        assert "frame_rate_marginal" in {f.code for f in result.flags}

    def test_unsupported_angle_is_soft_flag_admitted(self) -> None:
        result = run_quality_gate(measurements=_good_clip(), angle=_angle(supported=False))
        assert result.admitted is True  # angle never hard-fails (§5.1)
        assert "unsupported_camera_angle" in {f.code for f in result.flags}

    def test_some_blur_flag(self) -> None:
        assert "some_blur" in _codes(_measure(blur_score=0.5))


class TestAdmitRule:
    def test_any_fail_blocks_admission_even_with_flags(self) -> None:
        result = run_quality_gate(
            measurements=_measure(fps=25.0, exposure=0.05), angle=_angle(supported=False)
        )
        assert result.admitted is False  # underexposed fails despite soft flags
        assert "underexposed" in result.fail_reasons

    @pytest.mark.parametrize("duration", [2.0, 20.0])
    def test_duration_boundaries_ok(self, duration: float) -> None:
        result = run_quality_gate(measurements=_measure(duration_s=duration), angle=_angle())
        assert result.admitted is True
