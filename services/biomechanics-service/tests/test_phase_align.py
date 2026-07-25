"""Phase alignment (M10 Step 3, FR-M10-03)."""

from __future__ import annotations

from biomechanics_service.domain.phase_align import align_phases
from biomechanics_service.domain.stroke import Phases


def _phases(method: str = "standard") -> Phases:
    return Phases(stance=0, backlift=6, downswing=12, impact=18, follow_through=22, method=method)


class TestWindows:
    def test_windows_span_between_boundaries(self) -> None:
        aligned = align_phases(_phases(), frame_count=24)
        assert (aligned.stance.start, aligned.stance.end) == (0, 5)
        assert (aligned.backlift.start, aligned.backlift.end) == (6, 11)
        assert (aligned.downswing.start, aligned.downswing.end) == (12, 17)
        assert (aligned.follow_through.start, aligned.follow_through.end) == (18, 22)
        assert aligned.impact_frame == 18

    def test_windows_are_ordered_and_non_overlapping(self) -> None:
        aligned = align_phases(_phases(), frame_count=24)
        assert aligned.stance.end < aligned.backlift.start
        assert aligned.backlift.end < aligned.downswing.start
        assert aligned.downswing.end < aligned.follow_through.start

    def test_contains(self) -> None:
        aligned = align_phases(_phases(), frame_count=24)
        assert aligned.downswing.contains(14)
        assert not aligned.downswing.contains(18)

    def test_follow_through_runs_to_the_last_frame(self) -> None:
        aligned = align_phases(_phases(), frame_count=24)
        assert aligned.follow_through.end == 23 - 1  # last=23, follow start=18 end=22
        aligned2 = align_phases(
            Phases(
                stance=0, backlift=3, downswing=6, impact=9, follow_through=30, method="standard"
            ),
            frame_count=12,
        )
        assert aligned2.follow_through.end == 11  # clamped to last frame


class TestMethodPropagation:
    def test_standard_method_is_carried(self) -> None:
        assert align_phases(_phases("standard"), frame_count=24).method == "standard"

    def test_bat_only_fallback_is_carried(self) -> None:
        aligned = align_phases(_phases("bat_only_fallback"), frame_count=24)
        assert aligned.method == "bat_only_fallback"


class TestDegenerate:
    def test_collapsed_boundaries_yield_empty_windows_not_inverted(self) -> None:
        """A stroke M09 could barely segment must not produce inverted windows."""
        collapsed = Phases(
            stance=0,
            backlift=0,
            downswing=0,
            impact=0,
            follow_through=0,
            method="bat_only_fallback",
        )
        aligned = align_phases(collapsed, frame_count=20)
        assert aligned.stance.is_empty
        assert aligned.backlift.is_empty
        assert aligned.downswing.is_empty
        assert aligned.usable is False

    def test_out_of_order_boundaries_are_clamped_monotonic(self) -> None:
        messy = Phases(
            stance=5, backlift=2, downswing=18, impact=9, follow_through=25, method="standard"
        )
        aligned = align_phases(messy, frame_count=20)
        starts = [
            aligned.stance.start,
            aligned.backlift.start,
            aligned.downswing.start,
            aligned.impact_frame,
        ]
        assert starts == sorted(starts)

    def test_a_full_stroke_is_usable(self) -> None:
        assert align_phases(_phases(), frame_count=24).usable is True

    def test_empty_clip_does_not_crash(self) -> None:
        aligned = align_phases(_phases(), frame_count=0)
        assert aligned.impact_frame == 0
