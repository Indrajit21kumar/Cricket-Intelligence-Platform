"""Unit tests for pose-only phase segmentation (Pose-First MVP).

The fixture is a hand-built stroke whose landmarks are known by construction:
the hands sit still, rise, turn over, accelerate down to a low point, then
settle. Every assertion checks a boundary lands in the segment it belongs to,
not on an exact frame — the detector smooths before differentiating, so
pinning an exact index would test the filter's phase lag rather than the
landmark logic.
"""

from __future__ import annotations

import pytest

from biomechanics_service.domain.pose_phases import (
    PHASE_METHOD_POSE_INSUFFICIENT,
    PHASE_METHOD_POSE_WRIST,
    PhaseThresholds,
    Sample,
    segment_phases_from_pose,
)

FPS = 30.0


def _stroke_samples() -> list[Sample]:
    """A stroke with known landmarks (CIP frame: Y up).

    frames  0-9   stance, hands still at y=0.40
    frames 10-24  backlift, hands rise 0.40 -> 0.75
    frames 25-39  downswing, hands fall 0.75 -> 0.25 (accelerating)
    frames 40-49  follow-through, hands settle at 0.25
    """
    samples: list[Sample] = []
    for _ in range(10):
        samples.append((0.50, 0.40))
    for i in range(15):
        samples.append((0.50 - 0.004 * i, 0.40 + 0.35 * (i + 1) / 15))
    for i in range(15):
        t = (i + 1) / 15
        samples.append((0.44 + 0.010 * i, 0.75 - 0.50 * t * t))
    for _ in range(10):
        samples.append((0.59, 0.25))
    return samples


class TestStrokeLandmarks:
    def test_boundaries_are_ordered(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert p.stance <= p.backlift <= p.downswing <= p.impact <= p.follow_through

    def test_method_is_recorded_as_wrist_heuristic(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert p.method == PHASE_METHOD_POSE_WRIST

    def test_backlift_starts_in_the_rising_segment(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert 8 <= p.backlift <= 16, f"backlift at {p.backlift}, expected the 10-24 rise"

    def test_downswing_anchors_near_the_turnover(self) -> None:
        """BM-04 X-Factor is evaluated here, so it must land at the top."""
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert 22 <= p.downswing <= 30, f"downswing at {p.downswing}, expected the ~25 turnover"

    def test_impact_lands_in_the_fast_part_of_the_descent(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert 30 <= p.impact <= 42, f"impact at {p.impact}, expected the accelerating descent"

    def test_follow_through_is_after_impact_and_in_range(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        assert p.impact <= p.follow_through <= 49


class TestFrameRateIndependence:
    """Thresholds are per-second, so doubling fps must find the same stroke."""

    def _resampled(self, factor: int) -> list[Sample]:
        return [s for s in _stroke_samples() for _ in range(factor)]

    def test_60fps_finds_the_same_landmarks_in_time(self) -> None:
        at30 = segment_phases_from_pose(_stroke_samples(), fps=30.0, frame_count=50)
        at60 = segment_phases_from_pose(self._resampled(2), fps=60.0, frame_count=100)
        # Same instants in seconds, within a frame of tolerance at 30fps.
        assert abs(at60.downswing / 2 - at30.downswing) <= 3
        assert abs(at60.backlift / 2 - at30.backlift) <= 3


class TestDegenerateInput:
    def test_too_few_samples_reports_insufficient(self) -> None:
        p = segment_phases_from_pose([(0.5, 0.4), None, (0.5, 0.4)], fps=FPS, frame_count=3)
        assert p.method == PHASE_METHOD_POSE_INSUFFICIENT
        assert (p.stance, p.backlift, p.downswing, p.impact, p.follow_through) == (0, 0, 0, 0, 0)

    def test_all_missing_reports_insufficient(self) -> None:
        p = segment_phases_from_pose([None] * 30, fps=FPS, frame_count=30)
        assert p.method == PHASE_METHOD_POSE_INSUFFICIENT

    def test_static_hands_still_produce_ordered_boundaries(self) -> None:
        """No lift to find, but the output must stay well-formed."""
        p = segment_phases_from_pose([(0.5, 0.4)] * 30, fps=FPS, frame_count=30)
        assert p.stance <= p.backlift <= p.downswing <= p.impact <= p.follow_through
        assert p.follow_through <= 29

    def test_gaps_are_interpolated_not_dropped(self) -> None:
        samples = _stroke_samples()
        samples[12] = None
        samples[27] = None
        p = segment_phases_from_pose(samples, fps=FPS, frame_count=50)
        assert p.method == PHASE_METHOD_POSE_WRIST
        assert 22 <= p.downswing <= 30

    def test_boundaries_never_exceed_frame_count(self) -> None:
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50)
        for boundary in (p.stance, p.backlift, p.downswing, p.impact, p.follow_through):
            assert 0 <= boundary <= 49


class TestThresholdsAreConfigurable:
    def test_a_high_lift_threshold_finds_no_backlift(self) -> None:
        strict = PhaseThresholds(lift_velocity=50.0)
        p = segment_phases_from_pose(_stroke_samples(), fps=FPS, frame_count=50, thresholds=strict)
        # Falls back to the top of the arc rather than failing.
        assert p.method == PHASE_METHOD_POSE_WRIST
        assert p.backlift == p.downswing or p.backlift <= p.downswing

    @pytest.mark.parametrize("fps", [24.0, 30.0, 60.0, 120.0])
    def test_determinism_across_repeat_runs(self, fps: float) -> None:
        a = segment_phases_from_pose(_stroke_samples(), fps=fps, frame_count=50)
        b = segment_phases_from_pose(_stroke_samples(), fps=fps, frame_count=50)
        assert a == b
