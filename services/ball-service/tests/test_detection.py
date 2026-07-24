"""Ball detection under blur via motion cues (M08 Step 3, §11).

The decisive test is `test_static_clutter_is_rejected_however_confident`: a
ball is defined by how it MOVES, so an object that sits still must never be
tracked no matter how confidently the appearance detector reports it.
"""

from __future__ import annotations

import pytest

from ball_service.domain.ball import BallCandidate, FrameCandidates
from ball_service.domain.detection import (
    MIN_TRACK_LENGTH,
    build_track,
)
from ball_service.domain.tracker import FakeBallTracker

HEIGHT = 1000


def _frame(index: int, *candidates: tuple[float, float, float]) -> FrameCandidates:
    """Candidates given in frame-height units, converted to pixels."""
    return FrameCandidates(
        frame_index=index,
        candidates=tuple(
            BallCandidate(x=x * HEIGHT, y=y * HEIGHT, score=score) for x, y, score in candidates
        ),
    )


class TestMotionTracking:
    def test_a_moving_ball_is_tracked(self) -> None:
        frames = [_frame(i, (0.1 * i, 0.2 + 0.05 * i, 0.7)) for i in range(6)]
        track = build_track(frames, height=HEIGHT)
        assert track.frames_detected == 6
        assert track.positions[0].frame_index == 0

    def test_static_clutter_is_rejected_however_confident(self) -> None:
        """A round white object that never moves is a helmet, not a delivery."""
        frames = [
            _frame(
                i,
                (0.10 * i, 0.2 + 0.04 * i, 0.55),  # the real ball, less confident
                (0.50, 0.15, 0.99),  # static clutter, near-certain appearance
            )
            for i in range(6)
        ]
        track = build_track(frames, height=HEIGHT)
        assert track.frames_detected == 6
        # Every tracked point is the mover, not the confident static object.
        assert all(abs(p.y - 0.15) > 1e-6 for p in track.positions)

    def test_a_clip_with_only_static_objects_yields_nothing(self) -> None:
        """The fail-safe path depends on this returning empty, not guessing."""
        frames = [_frame(i, (0.5, 0.15, 0.99)) for i in range(8)]
        assert build_track(frames, height=HEIGHT).frames_detected == 0

    def test_no_candidates_at_all_yields_nothing(self) -> None:
        frames = [FrameCandidates(frame_index=i) for i in range(8)]
        assert build_track(frames, height=HEIGHT).frames_detected == 0


class TestGapsAndBlur:
    def test_a_blurred_out_frame_does_not_end_the_track(self) -> None:
        """The ball can vanish for a frame and rejoin the same trajectory."""
        frames = [
            _frame(0, (0.0, 0.20, 0.7)),
            _frame(1, (0.1, 0.25, 0.7)),
            FrameCandidates(frame_index=2),  # blurred out
            _frame(3, (0.3, 0.35, 0.7)),
            _frame(4, (0.4, 0.40, 0.7)),
        ]
        track = build_track(frames, height=HEIGHT)
        assert [p.frame_index for p in track.positions] == [0, 1, 3, 4]

    def test_streaks_are_carried_through_with_their_flag(self) -> None:
        frames = FakeBallTracker(blur_from=5).detect(frame_count=12, width=1920, height=1080)
        track = build_track(frames, height=1080)
        assert track.streak_ratio > 0.0
        assert any(p.streak for p in track.positions)
        assert any(not p.streak for p in track.positions)


class TestImplausibleMotion:
    def test_a_teleporting_candidate_is_not_followed(self) -> None:
        frames = [
            _frame(0, (0.10, 0.20, 0.8)),
            _frame(1, (0.15, 0.25, 0.8)),
            _frame(2, (0.95, 0.90, 0.9)),  # impossible single-frame jump
            _frame(3, (0.25, 0.35, 0.8)),
        ]
        track = build_track(frames, height=HEIGHT)
        assert all(p.x < 0.5 for p in track.positions)

    def test_a_sharp_reversal_is_rejected(self) -> None:
        frames = [
            _frame(0, (0.10, 0.20, 0.8)),
            _frame(1, (0.20, 0.30, 0.8)),
            _frame(2, (0.10, 0.20, 0.8)),  # doubles straight back
            _frame(3, (0.40, 0.50, 0.8)),
        ]
        track = build_track(frames, height=HEIGHT)
        xs = [p.x for p in track.positions]
        assert xs == sorted(xs)

    def test_the_bounce_reversal_survives(self) -> None:
        """The vertical flip at the bounce is signal, not noise — Step 4 needs it."""
        down = [_frame(i, (0.1 * i, 0.2 + 0.1 * i, 0.8)) for i in range(5)]
        up = [_frame(5 + i, (0.5 + 0.1 * i, 0.6 - 0.05 * i, 0.8)) for i in range(4)]
        track = build_track([*down, *up], height=HEIGHT)
        assert track.frames_detected == 9


class TestTrackLength:
    def test_a_track_shorter_than_the_minimum_is_discarded(self) -> None:
        frames = [_frame(i, (0.1 * i, 0.2 + 0.05 * i, 0.8)) for i in range(MIN_TRACK_LENGTH - 1)]
        assert build_track(frames, height=HEIGHT).frames_detected == 0

    def test_mean_confidence_is_reported_over_the_track(self) -> None:
        frames = [_frame(i, (0.1 * i, 0.2 + 0.05 * i, 0.6)) for i in range(5)]
        assert build_track(frames, height=HEIGHT).mean_confidence == pytest.approx(0.6)

    def test_empty_track_reports_zero_confidence_not_an_error(self) -> None:
        track = build_track([], height=HEIGHT)
        assert track.mean_confidence == 0.0
        assert track.streak_ratio == 0.0


class TestResolutionIndependence:
    def test_the_same_delivery_tracks_at_any_resolution(self) -> None:
        hd = FakeBallTracker().detect(frame_count=15, width=1920, height=1080)
        sd = FakeBallTracker().detect(frame_count=15, width=1280, height=720)
        assert (
            build_track(hd, height=1080).frames_detected
            == build_track(sd, height=720).frames_detected
        )
