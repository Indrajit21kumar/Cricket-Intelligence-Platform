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
