"""Degradation policy: the >30% downswing rule (M07 Step 6, AC-M07-03).

Boundary behaviour is the point of these tests. The spec says "more than 30%",
so exactly 30% must NOT trip the flag.
"""

from __future__ import annotations

import pytest

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    BatFrame,
    BatPart,
)
from bat_service.domain.degradation import (
    MAX_DOWNSWING_FAILURE_RATIO,
    assess,
    find_downswing,
)


def _frame(index: int, *, tip_y: float, detected: bool = True, confidence: float = 0.9) -> BatFrame:
    if not detected:
        return BatFrame(frame_index=index, detected=False)
    parts = (
        BatPart(part=HANDLE_BOTTOM, x=0.0, y=tip_y + 0.3, confidence=confidence),
        BatPart(part=BLADE_TIP, x=0.0, y=tip_y, confidence=confidence),
    )
    return BatFrame(frame_index=index, detected=True, parts=parts, confidence=confidence)


def _swing(
    *,
    length: int = 10,
    failed: frozenset[int] = frozenset(),
    confidence: float = 0.9,
) -> tuple[BatFrame, ...]:
    """A backlift (tip rising) then a downswing (tip falling) — a full arc."""
    peak = length // 3
    frames = []
    for i in range(length):
        tip_y = 0.1 * i if i <= peak else 0.1 * peak - 0.1 * (i - peak)
        frames.append(_frame(i, tip_y=tip_y, detected=i not in failed, confidence=confidence))
    return tuple(frames)


class TestDownswingWindow:
    def test_window_runs_from_backlift_top_to_lowest_point(self) -> None:
        frames = _swing(length=10)
        window = find_downswing(frames)
        assert window.basis == "motion"
        assert window.start == 3  # peak of the backlift
        assert window.end == 9  # lowest tip after it

    def test_too_little_detection_falls_back_to_the_whole_clip(self) -> None:
        """A wider window can only make the verdict more cautious."""
        frames = _swing(length=10, failed=frozenset(range(1, 10)))
        window = find_downswing(frames)
        assert window.basis == "whole_clip"
        assert (window.start, window.end) == (0, 9)

    def test_rising_only_track_falls_back(self) -> None:
        """If the bat is only ever seen going up, no downswing was observed."""
        frames = tuple(_frame(i, tip_y=0.05 * i) for i in range(6))
        assert find_downswing(frames).basis == "whole_clip"


class TestDegradationRule:
    def test_clean_track_is_ok(self) -> None:
        result = assess(_swing(length=10))
        assert result.provisional is False
        assert result.quality == QUALITY_OK
        assert result.reason is None

    def test_more_than_thirty_percent_downswing_failure_is_provisional(self) -> None:
        """AC-M07-03: the rule that M10 honours."""
        # Downswing is frames 3..9 (7 frames); 3 failures = 42.9% > 30%.
        result = assess(_swing(length=10, failed=frozenset({4, 6, 8})))
        assert result.downswing.basis == "motion"
        assert result.downswing_failures == 3
        assert result.downswing_failure_ratio > MAX_DOWNSWING_FAILURE_RATIO
        assert result.provisional is True
        assert result.quality == QUALITY_PROVISIONAL
        assert result.reason == "downswing_detection_gaps"

    def test_exactly_thirty_percent_is_not_provisional(self) -> None:
        """The spec says MORE than 30%, so the boundary itself passes."""
        # A purely descending track: window is 0..9 (10 frames), 3 failures.
        frames = tuple(_frame(i, tip_y=-0.05 * i, detected=i not in {3, 5, 7}) for i in range(10))
        result = assess(frames)
        assert result.downswing.length == 10
        assert result.downswing_failure_ratio == pytest.approx(0.30)
        assert result.provisional is False
        assert result.quality == QUALITY_OK

    def test_just_over_thirty_percent_trips_the_flag(self) -> None:
        frames = tuple(
            _frame(i, tip_y=-0.05 * i, detected=i not in {2, 3, 5, 7}) for i in range(10)
        )
        result = assess(frames)
        assert result.downswing_failure_ratio == pytest.approx(0.40)
        assert result.provisional is True

    def test_losing_the_bat_at_impact_is_not_hidden(self) -> None:
        """The worst failure: the track just stops partway down and never returns.

        The window must extend to the end of the clip, or those frames fall
        outside it and the rule silently reports a clean run.
        """
        frames = tuple(_frame(i, tip_y=-0.05 * i, detected=i <= 5) for i in range(10))
        result = assess(frames)
        assert result.downswing.end == 9
        assert result.downswing_failures == 4
        assert result.provisional is True
        assert result.reason == "downswing_detection_gaps"

    def test_failures_outside_the_downswing_do_not_trip_it(self) -> None:
        """A bat lost in the follow-through costs the metrics nothing."""
        frames = list(_swing(length=12))
        for i in (10, 11):  # after the lowest point
            frames[i] = BatFrame(frame_index=i, detected=False)
        result = assess(tuple(frames))
        assert result.provisional is False, result.reason


class TestOtherVerdicts:
    def test_no_detection_at_all_is_rejected(self) -> None:
        frames = tuple(BatFrame(frame_index=i, detected=False) for i in range(8))
        result = assess(frames)
        assert result.quality == QUALITY_REJECTED
        assert result.reason == "no_bat_detected"
        assert result.provisional is True

    def test_a_single_detected_frame_is_rejected(self) -> None:
        """One frame is not a bat track."""
        frames = (_frame(0, tip_y=0.2), *[BatFrame(frame_index=i, detected=False) for i in (1, 2)])
        assert assess(frames).quality == QUALITY_REJECTED

    def test_consistently_marginal_detection_is_provisional(self) -> None:
        """Every frame 'detected', none of them convincingly."""
        result = assess(_swing(length=10, confidence=0.3))
        assert result.provisional is True
        assert result.quality == QUALITY_PROVISIONAL
        assert result.reason == "low_detection_confidence"

    def test_mean_confidence_covers_detected_frames_only(self) -> None:
        result = assess(_swing(length=10, failed=frozenset({5}), confidence=0.8))
        assert result.mean_confidence == pytest.approx(0.8)
        assert result.frames_detected == 9
