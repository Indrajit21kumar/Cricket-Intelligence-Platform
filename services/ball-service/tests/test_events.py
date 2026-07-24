"""Event detection + line/length (M08 Step 4, AC-M08-01/02).

Written from synthetic trajectories per §13, so each event's own signal is
isolated: the bounce test has no bat, the contact tests vary only proximity and
turn, and release is tested from both ends of the ground.
"""

from __future__ import annotations

import pytest

from ball_service.domain.ball import (
    EVENT_BOUNCE,
    EVENT_CONTACT,
    EVENT_RELEASE,
    LENGTH_GOOD,
    LENGTH_SHORT,
    LENGTH_YORKER,
    LINE_MIDDLE,
    LINE_OUTSIDE_OFF,
    PROVENANCE_ESTIMATED,
    BallPosition,
)
from ball_service.domain.detection import BallTrack
from ball_service.domain.events import (
    StumpReference,
    classify_length,
    classify_line,
    detect_bounce,
    detect_contact,
    detect_release,
)

# 16:9 in frame-height units.
FRAME_WIDTH = 16 / 9


def _track(*points: tuple[int, float, float]) -> BallTrack:
    return BallTrack(
        positions=tuple(BallPosition(frame_index=i, x=x, y=y, confidence=0.8) for i, x, y in points)
    )


def _delivery(*, start_x: float = 0.1, frames: int = 9) -> BallTrack:
    """Descend to a bounce two-thirds through, then rise."""
    bounce_at = int(frames * 0.65)
    points = []
    for i in range(frames):
        x = start_x + 0.15 * i
        y = 0.30 + 0.09 * i if i <= bounce_at else 0.30 + 0.09 * bounce_at - 0.05 * (i - bounce_at)
        points.append((i, x, y))
    return _track(*points)


class TestRelease:
    def test_release_is_the_first_frame_when_the_track_starts_early(self) -> None:
        event = detect_release(_delivery(start_x=0.1), frame_width=FRAME_WIDTH)
        assert event is not None
        assert event.kind == EVENT_RELEASE
        assert event.frame_index == 0
        assert event.provenance == PROVENANCE_ESTIMATED

    def test_a_track_starting_mid_pitch_claims_no_release(self) -> None:
        """A false anchor would corrupt every release-relative timing in M10."""
        assert detect_release(_delivery(start_x=1.2), frame_width=FRAME_WIDTH) is None

    def test_right_to_left_footage_is_handled(self) -> None:
        """Direction of travel decides which edge counts — no mirroring flag."""
        mirrored = _track(*[(i, 1.7 - 0.15 * i, 0.3 + 0.05 * i) for i in range(8)])
        event = detect_release(mirrored, frame_width=FRAME_WIDTH)
        assert event is not None
        assert event.frame_index == 0

    def test_a_single_frame_is_not_a_release(self) -> None:
        assert detect_release(_track((0, 0.1, 0.3)), frame_width=FRAME_WIDTH) is None


class TestBounce:
    def test_the_reversal_frame_is_the_bounce(self) -> None:
        track = _delivery(frames=9)
        event = detect_bounce(track)
        assert event is not None
        assert event.kind == EVENT_BOUNCE
        # Lowest point (max pixel y) is frame 5 for a 9-frame delivery.
        assert event.frame_index == 5

    def test_a_ball_that_only_descends_has_no_bounce(self) -> None:
        descending = _track(*[(i, 0.1 * i, 0.2 + 0.08 * i) for i in range(6)])
        assert detect_bounce(descending) is None

    def test_jitter_is_not_a_bounce(self) -> None:
        """A 1px wobble must not be reported as the ball pitching."""
        flat = _track(*[(i, 0.1 * i, 0.50 + (0.002 if i == 3 else 0.0)) for i in range(7)])
        assert detect_bounce(flat) is None

    def test_bounce_confidence_is_bounded_by_the_frames_it_was_seen_in(self) -> None:
        positions = (
            BallPosition(frame_index=0, x=0.1, y=0.30, confidence=0.9),
            BallPosition(frame_index=1, x=0.3, y=0.50, confidence=0.9),
            BallPosition(frame_index=2, x=0.5, y=0.70, confidence=0.3),  # blurred
            BallPosition(frame_index=3, x=0.7, y=0.55, confidence=0.9),
        )
        event = detect_bounce(BallTrack(positions=positions))
        assert event is not None
        assert event.confidence == pytest.approx(0.3)

    def test_too_few_frames_yields_no_bounce(self) -> None:
        assert detect_bounce(_track((0, 0.1, 0.3), (1, 0.3, 0.6))) is None


class TestContact:
    def _struck(self) -> BallTrack:
        """Ball rises to the bat, then deflects sharply away."""
        return _track(
            (0, 0.60, 0.80),
            (1, 0.75, 0.65),
            (2, 0.90, 0.50),
            (3, 0.95, 0.75),  # deflected down/back after contact
            (4, 1.00, 0.95),
        )

    def test_proximity_plus_direction_change_is_contact(self) -> None:
        event = detect_contact(self._struck(), bat_positions={2: (0.90, 0.50)})
        assert event is not None
        assert event.kind == EVENT_CONTACT
        assert event.frame_index == 2

    def test_passing_the_bat_without_deflection_is_not_contact(self) -> None:
        """Proximity alone happens on every ball that beats the bat."""
        straight = _track(*[(i, 0.6 + 0.15 * i, 0.8 - 0.15 * i) for i in range(5)])
        assert detect_contact(straight, bat_positions={2: (0.90, 0.50)}) is None

    def test_a_direction_change_far_from_the_bat_is_not_contact(self) -> None:
        """That is the bounce, not a shot."""
        assert detect_contact(self._struck(), bat_positions={2: (0.10, 0.10)}) is None

    def test_without_m07_data_contact_is_not_claimed(self) -> None:
        assert detect_contact(self._struck(), bat_positions=None) is None
        assert detect_contact(self._struck(), bat_positions={}) is None


class TestLineAndLength:
    def _stumps(self) -> StumpReference:
        return StumpReference(stump_x=0.90, half_width=0.02, crease_x=1.00, pitch_span=1.00)

    def test_length_is_classified_from_a_side_on_camera(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        length, confidence = classify_length(
            bounce, track, stumps=self._stumps(), camera_angle="side_on"
        )
        assert length in {LENGTH_GOOD, LENGTH_SHORT, LENGTH_YORKER}
        assert confidence > 0.0

    def test_length_bands_move_with_the_bounce_point(self) -> None:
        stumps = self._stumps()
        near = _track((0, 0.1, 0.3), (1, 0.5, 0.6), (2, 0.99, 0.9), (3, 1.2, 0.6))
        far = _track((0, 0.1, 0.3), (1, 0.3, 0.6), (2, 0.40, 0.9), (3, 0.6, 0.6))
        near_length, _ = classify_length(
            detect_bounce(near), near, stumps=stumps, camera_angle="side_on"
        )
        far_length, _ = classify_length(
            detect_bounce(far), far, stumps=stumps, camera_angle="side_on"
        )
        assert near_length == LENGTH_YORKER
        assert far_length == LENGTH_SHORT

    def test_line_is_classified_from_a_front_on_camera(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        assert bounce is not None
        on_stumps = StumpReference(stump_x=_x_at(track, bounce.frame_index), half_width=0.02)
        line, confidence = classify_line(bounce, track, stumps=on_stumps, camera_angle="front_on")
        assert line == LINE_MIDDLE
        assert confidence > 0.0

    def test_line_bands_move_with_the_offset(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        assert bounce is not None
        wide = StumpReference(stump_x=_x_at(track, bounce.frame_index) + 0.30, half_width=0.02)
        line, _ = classify_line(bounce, track, stumps=wide, camera_angle="front_on")
        assert line == LINE_OUTSIDE_OFF


class TestCameraGeometryRefusals:
    def test_line_is_refused_from_side_on(self) -> None:
        """Side-on sees the across-pitch axis as depth — no line claim."""
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        stumps = StumpReference(stump_x=0.9, crease_x=1.0, pitch_span=1.0)
        assert classify_line(bounce, track, stumps=stumps, camera_angle="side_on") == (None, 0.0)

    def test_length_is_refused_from_front_on(self) -> None:
        """And front-on sees the down-pitch axis as depth — no length claim."""
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        stumps = StumpReference(stump_x=0.9, crease_x=1.0, pitch_span=1.0)
        assert classify_length(bounce, track, stumps=stumps, camera_angle="front_on") == (
            None,
            0.0,
        )

    def test_an_unsupported_angle_supports_neither(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        stumps = StumpReference(stump_x=0.9, crease_x=1.0, pitch_span=1.0)
        assert classify_line(bounce, track, stumps=stumps, camera_angle="square")[0] is None
        assert classify_length(bounce, track, stumps=stumps, camera_angle="square")[0] is None

    def test_no_bounce_means_no_line_or_length(self) -> None:
        descending = _track(*[(i, 0.1 * i, 0.2 + 0.08 * i) for i in range(6)])
        stumps = StumpReference(stump_x=0.9, crease_x=1.0, pitch_span=1.0)
        assert classify_line(None, descending, stumps=stumps, camera_angle="front_on")[0] is None
        assert classify_length(None, descending, stumps=stumps, camera_angle="side_on")[0] is None

    def test_no_stump_reference_means_no_claim(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        assert classify_line(bounce, track, stumps=None, camera_angle="front_on")[0] is None
        assert classify_length(bounce, track, stumps=None, camera_angle="side_on")[0] is None

    def test_length_without_a_crease_reference_is_refused(self) -> None:
        track = _delivery(frames=9)
        bounce = detect_bounce(track)
        no_crease = StumpReference(stump_x=0.9, crease_x=None, pitch_span=1.0)
        assert classify_length(bounce, track, stumps=no_crease, camera_angle="side_on")[0] is None


def _x_at(track: BallTrack, frame_index: int) -> float:
    return next(p.x for p in track.positions if p.frame_index == frame_index)
