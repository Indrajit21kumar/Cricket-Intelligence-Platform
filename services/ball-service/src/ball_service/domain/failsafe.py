"""Fail-safe assembly + timing fallback (M08 Step 6, NFR-M08-05, AC-M08-04/05).

This is the module's defining behaviour, so it is a single explicit gate that
every result passes through rather than a rule scattered across the detectors.

Two guarantees, and they compose:

1. **Nothing is fabricated.** When conditions or tracking are too poor, the
   result is empty — no release, no bounce, no contact, no line, no length, no
   speed. Not zeroes, not "unknown" placeholders: absent. The types make that
   representable (:class:`BallEvents` fields are all optional), and this module
   is what enforces it.
2. **Timing degrades, it does not lie.** ``timing_reference`` is
   ``release_relative`` only when release was actually detected AND clears a
   confidence floor. Otherwise it is ``absolute``, which M10 honours by
   switching to absolute timing and its bat-only phase segmentation
   (REQ-BIO-008, §8).

The ordering matters: conditions are checked first, because a clip that failed
the capture gate must not be rescued by a tracker that happens to report high
confidence on it. The ceiling from Step 2 is applied to ``track_confidence``
before anything is decided, so optimism downstream cannot outvote the physics
of the capture.

One deliberate asymmetry: a POOR-conditions clip is suppressed entirely, while
a GOOD-conditions clip that simply had no ball in shot returns empty results
with normal confidence handling. Both are empty, but only the first is a
warning about the capture — and ``conditions_met`` is what tells them apart for
the user-facing message.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ball_service.domain.ball import (
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    TIMING_ABSOLUTE,
    TIMING_RELEASE_RELATIVE,
    BallEvents,
)
from ball_service.domain.conditions import ConditionAssessment
from ball_service.domain.detection import BallTrack

#: Release must be at least this confident to anchor release-relative timing.
#: A shaky release frame is worse than none: M10 would compute every phase
#: against it and report the error as precision.
MIN_RELEASE_CONFIDENCE = 0.45

#: Below this overall track confidence, results are suppressed entirely.
MIN_TRACK_CONFIDENCE = 0.20

#: Below this, results are kept but marked provisional.
PROVISIONAL_TRACK_CONFIDENCE = 0.50

#: A track covering less of the clip than this is too sparse to trust.
MIN_COVERAGE = 0.25


@dataclass(frozen=True, slots=True)
class FailSafeResult:
    events: BallEvents
    track_confidence: float
    quality: str
    conditions_met: bool
    #: Stable slugs explaining suppression or degradation; empty when clean.
    reasons: tuple[str, ...]

    @property
    def suppressed(self) -> bool:
        """True when M08 declined to report anything about the ball."""
        return self.events.is_empty


def _empty(
    *,
    conditions_met: bool,
    confidence: float,
    reasons: tuple[str, ...],
    quality: str,
) -> FailSafeResult:
    return FailSafeResult(
        # timing_reference defaults to absolute — the safe value — so an empty
        # result cannot promise M10 timing that was never established.
        events=BallEvents(),
        track_confidence=confidence,
        quality=quality,
        conditions_met=conditions_met,
        reasons=reasons,
    )


def apply_failsafe(
    events: BallEvents,
    *,
    track: BallTrack,
    conditions: ConditionAssessment,
    frame_count: int,
) -> FailSafeResult:
    """Gate a candidate result. Suppresses rather than fabricates."""
    reasons: list[str] = []

    # The capture ceiling binds first: a clip that cannot support tracking must
    # not be rescued by a confident tracker.
    confidence = min(track.mean_confidence, conditions.confidence_ceiling)
    if conditions.limits:
        reasons.extend(conditions.limits)

    if not conditions.met:
        reasons.append("capture_conditions_unsupported")
        return _empty(
            conditions_met=False,
            confidence=confidence,
            reasons=tuple(reasons),
            quality=QUALITY_REJECTED,
        )

    coverage = (track.frames_detected / frame_count) if frame_count else 0.0
    if track.frames_detected == 0:
        reasons.append("no_ball_detected")
        return _empty(
            conditions_met=True,
            confidence=0.0,
            reasons=tuple(reasons),
            quality=QUALITY_REJECTED,
        )

    if coverage < MIN_COVERAGE:
        reasons.append("track_too_sparse")
        return _empty(
            conditions_met=True,
            confidence=confidence,
            reasons=tuple(reasons),
            quality=QUALITY_REJECTED,
        )

    if confidence < MIN_TRACK_CONFIDENCE:
        reasons.append("track_confidence_below_floor")
        return _empty(
            conditions_met=True,
            confidence=confidence,
            reasons=tuple(reasons),
            quality=QUALITY_REJECTED,
        )

    # Timing: release-relative has to be earned, twice over — the event must
    # exist AND be confident enough to anchor every phase M10 derives from it.
    release = events.release
    if release is None:
        reasons.append("release_not_detected")
        timing = TIMING_ABSOLUTE
    elif release.confidence < MIN_RELEASE_CONFIDENCE:
        reasons.append("release_confidence_below_floor")
        # The release frame stays in the output as a weak observation, but it
        # is explicitly not used as a timing anchor.
        timing = TIMING_ABSOLUTE
    else:
        timing = TIMING_RELEASE_RELATIVE

    quality = QUALITY_OK if confidence >= PROVISIONAL_TRACK_CONFIDENCE else QUALITY_PROVISIONAL
    if quality == QUALITY_PROVISIONAL:
        reasons.append("low_track_confidence")

    return FailSafeResult(
        events=replace(events, timing_reference=timing),
        track_confidence=confidence,
        quality=quality,
        conditions_met=True,
        reasons=tuple(reasons),
    )
