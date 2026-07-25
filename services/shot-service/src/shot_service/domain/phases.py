"""Phase segmentation: stance → backlift → downswing → impact → follow-through.

M09 Step 4, FR-M09-03/05, AC-M09-03/04. Implements the biomechanics phase model
(REQ-BIO-007) as a boundary finder over the hands' vertical motion, with the
impact frame anchored two different ways depending on what M08 supplied — and,
crucially, the module RECORDS which (``phase_method``), because M10 trusts a
ball-anchored impact differently from a bat-inferred one.

Method selection (AC-M09-04) is a single hinge:

- **standard** — M08 gave a *usable* contact frame, meaning a contact event was
  detected AND M08 anchored to release rather than its absolute-timing
  fallback. Impact is that frame. This is the only case where impact rests on
  external ball evidence.
- **bat_only_fallback** — otherwise. Impact is inferred from the body alone:
  the hands' lowest point on the downswing (the strike zone), which is where
  the bat meets a ball travelling into it. This is REQ-BIO-008's fallback, and
  it is the same fallback M08→M10 already use, kept consistent here.

The boundaries are the hands' motion landmarks around that impact:
- stance: the clip start.
- backlift: hands begin rising (start of upward motion).
- downswing: hands turn over at the top and begin descending.
- impact: the ball frame (standard) or the hands' low point (fallback).
- follow_through: the first frame after impact.

They are forced monotonic non-decreasing: a real stroke cannot run its phases
out of order, so a degenerate clip collapses phases onto the same frame rather
than emitting a backlift that starts after impact.
"""

from __future__ import annotations

from shot_service.domain.shot import (
    METHOD_BAT_ONLY_FALLBACK,
    METHOD_STANDARD,
    PhaseBoundaries,
)
from shot_service.domain.sources import LEFT_WRIST, RIGHT_WRIST, BallSummary, PoseSequence


def _hand_heights(pose: PoseSequence) -> list[tuple[int, float]]:
    """(frame_index, hands_y) for every frame where the hands are visible."""
    out: list[tuple[int, float]] = []
    for frame in pose.frames:
        hands = frame.midpoint(LEFT_WRIST, RIGHT_WRIST)
        if hands is not None:
            out.append((frame.frame_index, hands[1]))
    return out


def _clamp_monotonic(*boundaries: int, last: int) -> tuple[int, ...]:
    """Force a non-decreasing, in-range sequence.

    A stroke's phases cannot run out of order, so a degenerate clip collapses
    boundaries onto each other rather than emitting an impossible timeline.
    """
    result: list[int] = []
    current = 0
    for b in boundaries:
        current = max(current, min(max(b, 0), last))
        result.append(current)
    return tuple(result)


def segment_phases(
    pose: PoseSequence,
    *,
    ball: BallSummary | None,
) -> PhaseBoundaries:
    """Find the five phase boundaries; anchor impact on ball or bat.

    Returns a zeroed, fallback-method segmentation when the pose is too sparse
    to find landmarks — honest about having nothing rather than inventing a
    plausible-looking timeline.
    """
    heights = _hand_heights(pose)
    last = (pose.frame_count - 1) if pose.frame_count else 0

    if len(heights) < 3:
        return PhaseBoundaries(
            stance=0,
            backlift=0,
            downswing=0,
            impact=0,
            follow_through=0,
            method=METHOD_BAT_ONLY_FALLBACK,
        )

    # Top of the backlift: the highest the hands reach (CIP Y-up).
    top_pos = max(range(len(heights)), key=lambda i: heights[i][1])

    # Backlift starts when the hands first begin rising toward that top.
    backlift_idx = heights[0][0]
    for i in range(1, top_pos + 1):
        if heights[i][1] > heights[i - 1][1]:
            backlift_idx = heights[i - 1][0]
            break

    # Downswing starts at the top of the backlift.
    downswing_idx = heights[top_pos][0]

    # Impact: ball-anchored when M08 gave a usable contact, else the hands'
    # lowest point AFTER the top (the strike zone on the way down).
    method = METHOD_BAT_ONLY_FALLBACK
    impact_idx: int
    if ball is not None and ball.usable_contact and ball.contact_frame is not None:
        impact_idx = ball.contact_frame
        method = METHOD_STANDARD
    else:
        after_top = heights[top_pos:]
        if len(after_top) >= 2:
            low_pos = min(range(len(after_top)), key=lambda i: after_top[i][1])
            impact_idx = after_top[low_pos][0]
        else:
            impact_idx = heights[-1][0]

    follow_idx = min(impact_idx + 1, last)

    stance, backlift, downswing, impact, follow = _clamp_monotonic(
        0, backlift_idx, downswing_idx, impact_idx, follow_idx, last=last
    )
    return PhaseBoundaries(
        stance=stance,
        backlift=backlift,
        downswing=downswing,
        impact=impact,
        follow_through=follow,
        method=method,
    )
