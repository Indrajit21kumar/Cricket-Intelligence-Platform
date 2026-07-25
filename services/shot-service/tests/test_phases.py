"""Phase segmentation (M09 Step 4, AC-M09-03/04).

Two things carry the acceptance criteria: boundaries are monotonic frame
indices for all five phases, and phase_method tracks M08's state exactly —
standard only when M08 gave a usable, release-anchored contact.
"""

from __future__ import annotations

import math

from shot_service.domain.phases import segment_phases
from shot_service.domain.shot import (
    METHOD_BAT_ONLY_FALLBACK,
    METHOD_STANDARD,
    PHASE_ORDER,
)
from shot_service.domain.sources import BallSummary, PoseFrame, PoseSequence


def _pose(frames: int = 24) -> PoseSequence:
    """Hands rise to a backlift top ~1/3 in, then descend through impact."""
    top = frames // 3
    seq = []
    for i in range(frames):
        y = 0.6 + 0.5 * (i / top) if i <= top else 1.1 - 0.7 * ((i - top) / (frames - 1 - top))
        seq.append(
            PoseFrame(
                frame_index=i,
                joints={
                    "left_wrist": (0.1 * math.sin(i), y, 0.9),
                    "right_wrist": (0.1 * math.sin(i) + 0.02, y, 0.9),
                },
            )
        )
    return PoseSequence(frames=tuple(seq))


def _ball(*, contact_frame: int | None, timing: str, conditions_met: bool = True) -> BallSummary:
    return BallSummary(
        contact_frame=contact_frame,
        timing_reference=timing,
        line=None,
        length=None,
        conditions_met=conditions_met,
    )


class TestBoundaries:
    def test_five_phases_as_monotonic_frame_indices(self) -> None:
        """AC-M09-03."""
        phases = segment_phases(_pose(24), ball=None)
        as_dict = phases.as_dict()
        assert set(as_dict) == set(PHASE_ORDER)
        assert all(isinstance(v, int) for v in as_dict.values())
        assert phases.is_monotonic

    def test_backlift_precedes_downswing_precedes_impact(self) -> None:
        phases = segment_phases(_pose(24), ball=None)
        assert phases.stance <= phases.backlift < phases.downswing
        assert phases.downswing < phases.impact <= phases.follow_through

    def test_follow_through_never_exceeds_the_last_frame(self) -> None:
        phases = segment_phases(_pose(10), ball=None)
        assert phases.follow_through <= 9


class TestMethodSelection:
    def test_a_usable_contact_gives_standard_anchored_on_it(self) -> None:
        """AC-M09-04: ball-anchored impact."""
        phases = segment_phases(
            _pose(24),
            ball=_ball(contact_frame=17, timing="release_relative"),
        )
        assert phases.method == METHOD_STANDARD
        assert phases.impact == 17

    def test_absolute_timing_forces_bat_only_fallback(self) -> None:
        """M08 fell back to absolute timing, so its contact is not trusted."""
        phases = segment_phases(
            _pose(24),
            ball=_ball(contact_frame=17, timing="absolute"),
        )
        assert phases.method == METHOD_BAT_ONLY_FALLBACK
        # Impact is inferred from the body, not the (untrusted) ball frame.
        assert phases.impact != 17

    def test_no_ball_at_all_is_bat_only_fallback(self) -> None:
        """AC-M09-05 companion: pose-only still segments."""
        phases = segment_phases(_pose(24), ball=None)
        assert phases.method == METHOD_BAT_ONLY_FALLBACK
        assert phases.is_monotonic

    def test_poor_conditions_contact_is_not_used(self) -> None:
        phases = segment_phases(
            _pose(24),
            ball=_ball(contact_frame=17, timing="release_relative", conditions_met=False),
        )
        assert phases.method == METHOD_BAT_ONLY_FALLBACK

    def test_fallback_impact_is_the_hands_low_point_on_the_downswing(self) -> None:
        phases = segment_phases(_pose(24), ball=None)
        # The synthetic stroke bottoms out at the final frame.
        assert phases.impact >= phases.downswing


class TestDegenerate:
    def test_too_sparse_a_pose_collapses_to_a_zeroed_fallback(self) -> None:
        """Honest about having nothing, rather than inventing a timeline."""
        sparse = PoseSequence(
            frames=(PoseFrame(frame_index=0, joints={"left_wrist": (0.0, 0.6, 0.9)}),)
        )
        phases = segment_phases(sparse, ball=None)
        assert phases.method == METHOD_BAT_ONLY_FALLBACK
        assert phases.as_dict() == dict.fromkeys(PHASE_ORDER, 0)

    def test_an_out_of_order_ball_contact_is_clamped_monotonic(self) -> None:
        """A contact frame before the downswing must not invert the timeline."""
        phases = segment_phases(
            _pose(24),
            ball=_ball(contact_frame=1, timing="release_relative"),
        )
        assert phases.is_monotonic
        assert phases.impact >= phases.downswing
