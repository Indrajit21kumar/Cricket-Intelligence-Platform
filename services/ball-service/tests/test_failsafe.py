"""Fail-safe + timing fallback (M08 Step 6, AC-M08-04/05).

The tests that matter most assert ABSENCE: on poor clips nothing may be
reported, and no path may promise release-relative timing without a release
frame good enough to anchor it.
"""

from __future__ import annotations

import pytest

from ball_service.domain.ball import (
    EVENT_BOUNCE,
    EVENT_RELEASE,
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    TIMING_ABSOLUTE,
    TIMING_RELEASE_RELATIVE,
    BallEvent,
    BallEvents,
    BallPosition,
    SpeedEstimate,
)
from ball_service.domain.conditions import (
    CEILING_MARGINAL,
    CEILING_SUPPORTED,
    CEILING_UNSUPPORTED,
    PROFILE_MARGINAL,
    PROFILE_SUPPORTED,
    PROFILE_UNSUPPORTED,
    ConditionAssessment,
)
from ball_service.domain.detection import BallTrack
from ball_service.domain.failsafe import (
    MIN_RELEASE_CONFIDENCE,
    apply_failsafe,
)

FRAME_COUNT = 12


def _track(*, frames: int = 10, confidence: float = 0.8) -> BallTrack:
    return BallTrack(
        positions=tuple(
            BallPosition(frame_index=i, x=0.1 * i, y=0.3 + 0.05 * i, confidence=confidence)
            for i in range(frames)
        )
    )


def _conditions(
    profile: str = PROFILE_SUPPORTED,
    ceiling: float = CEILING_SUPPORTED,
    limits: tuple[str, ...] = (),
) -> ConditionAssessment:
    return ConditionAssessment(profile=profile, confidence_ceiling=ceiling, limits=limits)


def _full_events(release_confidence: float = 0.8) -> BallEvents:
    return BallEvents(
        release=BallEvent(kind=EVENT_RELEASE, frame_index=0, confidence=release_confidence),
        bounce=BallEvent(kind=EVENT_BOUNCE, frame_index=6, confidence=0.8),
        line="middle_stump",
        line_confidence=0.8,
        speed=SpeedEstimate(metres_per_second=32.0, confidence=0.6),
    )


class TestGoodClips:
    def test_a_clean_clip_keeps_everything_and_earns_release_relative(self) -> None:
        result = apply_failsafe(
            _full_events(),
            track=_track(),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.quality == QUALITY_OK
        assert result.events.timing_reference == TIMING_RELEASE_RELATIVE
        assert result.events.release is not None
        assert result.events.speed is not None
        assert result.suppressed is False
        assert result.conditions_met is True

    def test_marginal_conditions_cap_confidence_and_mark_provisional(self) -> None:
        result = apply_failsafe(
            _full_events(),
            track=_track(confidence=0.95),
            conditions=_conditions(PROFILE_MARGINAL, CEILING_MARGINAL, ("fps_marginal",)),
            frame_count=FRAME_COUNT,
        )
        # The tracker claimed 0.95; the capture only supports 0.60.
        assert result.track_confidence == pytest.approx(CEILING_MARGINAL)
        assert "fps_marginal" in result.reasons


class TestNothingIsFabricated:
    def test_unsupported_conditions_suppress_every_event(self) -> None:
        """AC-M08-05: on deliberately poor clips, no fabricated events."""
        result = apply_failsafe(
            _full_events(),
            track=_track(confidence=0.9),
            conditions=_conditions(PROFILE_UNSUPPORTED, CEILING_UNSUPPORTED, ("fps_below_floor",)),
            frame_count=FRAME_COUNT,
        )
        assert result.suppressed is True
        assert result.events.release is None
        assert result.events.bounce is None
        assert result.events.contact is None
        assert result.events.line is None
        assert result.events.length is None
        assert result.events.speed is None
        assert result.quality == QUALITY_REJECTED
        assert result.conditions_met is False
        assert "capture_conditions_unsupported" in result.reasons

    def test_a_confident_tracker_cannot_rescue_a_bad_clip(self) -> None:
        """The capture ceiling binds first, by design."""
        result = apply_failsafe(
            _full_events(),
            track=_track(confidence=1.0),
            conditions=_conditions(PROFILE_UNSUPPORTED, CEILING_UNSUPPORTED, ("excessive_blur",)),
            frame_count=FRAME_COUNT,
        )
        assert result.suppressed is True
        assert result.track_confidence <= CEILING_UNSUPPORTED

    def test_no_ball_detected_reports_nothing(self) -> None:
        result = apply_failsafe(
            BallEvents(),
            track=BallTrack(positions=()),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.suppressed is True
        assert result.quality == QUALITY_REJECTED
        assert "no_ball_detected" in result.reasons
        # Good conditions, just no ball — distinguishable from a bad clip.
        assert result.conditions_met is True

    def test_a_sparse_track_is_suppressed(self) -> None:
        """Two frames out of twelve is not evidence of a delivery."""
        result = apply_failsafe(
            _full_events(),
            track=_track(frames=2),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.suppressed is True
        assert "track_too_sparse" in result.reasons

    def test_confidence_below_the_floor_is_suppressed(self) -> None:
        result = apply_failsafe(
            _full_events(),
            track=_track(confidence=0.10),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.suppressed is True
        assert "track_confidence_below_floor" in result.reasons

    def test_a_suppressed_result_still_reports_absolute_timing(self) -> None:
        """An empty result must not promise timing it never established."""
        result = apply_failsafe(
            _full_events(),
            track=_track(),
            conditions=_conditions(PROFILE_UNSUPPORTED, CEILING_UNSUPPORTED),
            frame_count=FRAME_COUNT,
        )
        assert result.events.timing_reference == TIMING_ABSOLUTE


class TestTimingFallback:
    def test_no_release_means_absolute_timing(self) -> None:
        """AC-M08-04: M10 falls back to absolute timing."""
        events = BallEvents(bounce=BallEvent(kind=EVENT_BOUNCE, frame_index=6, confidence=0.8))
        result = apply_failsafe(
            events, track=_track(), conditions=_conditions(), frame_count=FRAME_COUNT
        )
        assert result.events.timing_reference == TIMING_ABSOLUTE
        assert "release_not_detected" in result.reasons
        # The bounce survives — only the timing anchor is missing.
        assert result.events.bounce is not None

    def test_a_weak_release_does_not_anchor_timing(self) -> None:
        """A shaky anchor is worse than none: M10 would report error as precision."""
        result = apply_failsafe(
            _full_events(release_confidence=MIN_RELEASE_CONFIDENCE - 0.05),
            track=_track(),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.events.timing_reference == TIMING_ABSOLUTE
        assert "release_confidence_below_floor" in result.reasons
        # Kept as a weak observation, but explicitly not used as the anchor.
        assert result.events.release is not None

    def test_the_release_confidence_boundary_earns_the_anchor(self) -> None:
        result = apply_failsafe(
            _full_events(release_confidence=MIN_RELEASE_CONFIDENCE),
            track=_track(),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.events.timing_reference == TIMING_RELEASE_RELATIVE


class TestQualityBanding:
    def test_low_confidence_is_provisional_not_rejected(self) -> None:
        result = apply_failsafe(
            _full_events(),
            track=_track(confidence=0.35),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.quality == QUALITY_PROVISIONAL
        assert result.suppressed is False  # kept, but flagged
        assert "low_track_confidence" in result.reasons

    def test_reasons_are_empty_on_a_clean_run(self) -> None:
        result = apply_failsafe(
            _full_events(),
            track=_track(),
            conditions=_conditions(),
            frame_count=FRAME_COUNT,
        )
        assert result.reasons == ()
