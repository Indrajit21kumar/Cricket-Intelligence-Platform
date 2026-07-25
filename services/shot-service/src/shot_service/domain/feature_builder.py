"""Build the shot feature vector from pose (+ optional bat/ball) (M09 Step 2).

Pose gives the body's motion; bat and ball, when present, add the two signals
pose cannot supply — the bat's swing plane and the ball's line. The builder's
contract is FR-M09-04: it produces a vector from whatever is available, records
which signals contributed, and never substitutes a zero for an absent one.

All pose maths is in the CIP frame M06 already produced: origin at the ground
beneath mid-stance, Y up, scaled by frame height. So a wrist ``y`` is a height
above the ground in resolution-independent units, and heights compare directly
across clips without any further calibration.

The stroke's "swing frame" — where the hands move fastest — is used as the
impact proxy for contact height and footedness. It is a proxy on purpose:
precise impact is M08's contact frame (used in Step 4's phase segmentation),
but the feature builder must work pose-only, so it derives its own moment from
the body alone.
"""

from __future__ import annotations

import math

from shot_service.domain.features import ShotFeatures
from shot_service.domain.shot import SIGNAL_BALL, SIGNAL_BAT, SIGNAL_POSE
from shot_service.domain.sources import (
    LEFT_ANKLE,
    LEFT_HIP,
    LEFT_SHOULDER,
    LEFT_WRIST,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    BallSummary,
    BatSummary,
    PoseFrame,
    PoseSequence,
)

#: Scales forward lean (CIP units) into the [-1, 1] footedness range.
FOOTEDNESS_GAIN = 6.0


def _hands(frame: PoseFrame) -> tuple[float, float] | None:
    """Midpoint of the two wrists — a batter's hands are together on the bat."""
    return frame.midpoint(LEFT_WRIST, RIGHT_WRIST)


def _shoulder_angle(frame: PoseFrame) -> float | None:
    """Angle of the shoulder line, degrees — its range measures rotation."""
    ls, rs = frame.point(LEFT_SHOULDER), frame.point(RIGHT_SHOULDER)
    if ls is None or rs is None:
        return None
    return math.degrees(math.atan2(rs[1] - ls[1], rs[0] - ls[0]))


def _swing_frame_index(sequence: PoseSequence) -> int:
    """Index of peak hand speed — the impact proxy when no ball frame exists."""
    best_index = 0
    best_speed = -1.0
    previous: tuple[float, float] | None = None
    for i, frame in enumerate(sequence.frames):
        hands = _hands(frame)
        if hands is None:
            continue
        if previous is not None:
            speed = math.hypot(hands[0] - previous[0], hands[1] - previous[1])
            if speed > best_speed:
                best_speed, best_index = speed, i
        previous = hands
    return best_index


def build_features(
    pose: PoseSequence,
    *,
    bat: BatSummary | None = None,
    ball: BallSummary | None = None,
) -> ShotFeatures:
    """Fuse pose with bat/ball where present; degrade to pose-only otherwise."""
    signals: list[str] = [SIGNAL_POSE]

    hand_points = [h for f in pose.frames if (h := _hands(f)) is not None]
    hand_ys = [h[1] for h in hand_points]

    wrist_peak_height = max(hand_ys) if hand_ys else 0.0

    angles = [a for f in pose.frames if (a := _shoulder_angle(f)) is not None]
    shoulder_rotation = (max(angles) - min(angles)) if angles else 0.0

    # SIGNED lateral displacement across the stroke (end minus start): which
    # SIDE the hands finished, since that is what tells a cover drive from an
    # on drive. Net, not peak-speed-relative, so it is robust to where the
    # fastest frame happens to fall.
    wrist_lateral_travel = (hand_points[-1][0] - hand_points[0][0]) if hand_points else 0.0

    swing = pose.frames[_swing_frame_index(pose)] if pose.frames else None
    contact_height = 0.0
    footedness = 0.0
    if swing is not None:
        hands = _hands(swing)
        if hands is not None:
            contact_height = hands[1]
        hip = swing.midpoint(LEFT_HIP, RIGHT_HIP)
        ankle = swing.midpoint(LEFT_ANKLE, RIGHT_ANKLE)
        if hip is not None and ankle is not None:
            # Hips ahead of the base = weight forward = front-foot commitment.
            footedness = max(-1.0, min(1.0, (hip[0] - ankle[0]) * FOOTEDNESS_GAIN))

    swing_plane_inclination: float | None = None
    bat_angle_range: float | None = None
    if bat is not None:
        signals.append(SIGNAL_BAT)
        swing_plane_inclination = bat.swing_plane_inclination

    ball_line: str | None = None
    ball_length: str | None = None
    if ball is not None:
        signals.append(SIGNAL_BALL)
        ball_line = ball.line
        ball_length = ball.length

    return ShotFeatures(
        frame_count=pose.frame_count,
        signals=tuple(signals),
        footedness=footedness,
        wrist_peak_height=wrist_peak_height,
        wrist_lateral_travel=wrist_lateral_travel,
        shoulder_rotation=shoulder_rotation,
        contact_height=contact_height,
        swing_plane_inclination=swing_plane_inclination,
        bat_angle_range=bat_angle_range,
        ball_line=ball_line,
        ball_length=ball_length,
    )
