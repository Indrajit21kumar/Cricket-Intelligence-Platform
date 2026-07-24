"""Capture-condition gate (M08 Step 2, FR-M08-05).

Runs BEFORE any tracking. The spec is explicit that M08 "works reliably only
under good capture conditions" (§1) and that sub-threshold clips must be
flagged low-confidence "up front" — not tracked hopefully and explained away
afterwards. Deciding first is what makes the difference honest: a clip that
fails the gate gets a low ceiling on its confidence no matter how confident
the tracker later claims to be.

Thresholds are M08's own, and deliberately STRICTER than M05's. M05 asks "is
this clip usable for coaching at all?", which a 24fps clip is — the body moves
slowly enough. M08 asks "can a ball travelling 100+ km/h be located frame to
frame?", which at 24fps it cannot: the ball moves metres between frames and
the events M08 exists to find are smeared into invisibility. So a clip M05
admitted may still fail M08's gate, and that is correct rather than a
contradiction.

The gate reads what M05 published — ``fps`` plus the quality-flag codes — and
does not re-measure the video. M05 owns clip measurement; duplicating it here
would let the two drift.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Below this the ball is unlocatable frame to frame — no useful tracking.
FPS_HARD_FLOOR = 24.0
#: Below this, tracking is possible but events and speed degrade sharply.
FPS_PREFERRED = 50.0

#: M05 flag codes that matter to ball tracking specifically.
BLUR_FAIL_CODES = frozenset({"excessive_blur"})
BLUR_WARN_CODES = frozenset({"some_blur"})
LIGHT_FAIL_CODES = frozenset({"too_dark", "overexposed", "poor_lighting"})
LIGHT_WARN_CODES = frozenset({"low_light", "marginal_lighting"})
FPS_WARN_CODES = frozenset({"frame_rate_marginal"})
FPS_FAIL_CODES = frozenset({"frame_rate_too_low"})

#: Confidence ceilings. A clip cannot report more confidence than its capture
#: conditions can support, whatever the tracker says.
CEILING_UNSUPPORTED = 0.25
CEILING_MARGINAL = 0.60
CEILING_SUPPORTED = 1.0

# Condition profiles, in the spec's language (§13 "supported condition profile").
PROFILE_SUPPORTED = "supported"
PROFILE_MARGINAL = "marginal"
PROFILE_UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class ConditionAssessment:
    """What the capture allows, decided before any tracking happens."""

    profile: str  # supported | marginal | unsupported
    #: Upper bound on track_confidence for this clip.
    confidence_ceiling: float
    #: Stable slugs naming every condition that limited the clip.
    limits: tuple[str, ...]

    @property
    def met(self) -> bool:
        """True when conditions support ball tracking at all."""
        return self.profile != PROFILE_UNSUPPORTED


def _codes(quality_flags: list[dict[str, Any]] | None) -> set[str]:
    return {str(f.get("code")) for f in (quality_flags or []) if f.get("code")}


def assess_conditions(
    *,
    fps: float | None,
    quality_flags: list[dict[str, Any]] | None = None,
    pixel_to_meter: float | None = None,
    spatial_confidence: str | None = None,
) -> ConditionAssessment:
    """Decide what this clip's capture conditions permit, before tracking.

    Missing fps is treated as unsupported rather than assumed good: M08 cannot
    turn displacement into speed without it, and guessing a frame rate would
    fabricate the very number the estimate depends on.
    """
    limits: list[str] = []
    codes = _codes(quality_flags)

    if fps is None:
        limits.append("fps_unknown")
        return ConditionAssessment(
            profile=PROFILE_UNSUPPORTED,
            confidence_ceiling=CEILING_UNSUPPORTED,
            limits=tuple(limits),
        )

    unsupported = False
    marginal = False

    if fps < FPS_HARD_FLOOR or codes & FPS_FAIL_CODES:
        limits.append("fps_below_floor")
        unsupported = True
    elif fps < FPS_PREFERRED or codes & FPS_WARN_CODES:
        limits.append("fps_marginal")
        marginal = True

    if codes & BLUR_FAIL_CODES:
        limits.append("excessive_blur")
        unsupported = True
    elif codes & BLUR_WARN_CODES:
        limits.append("some_blur")
        marginal = True

    if codes & LIGHT_FAIL_CODES:
        limits.append("poor_lighting")
        unsupported = True
    elif codes & LIGHT_WARN_CODES:
        limits.append("marginal_lighting")
        marginal = True

    # Without calibration a position is still trackable, but nothing metric
    # can be derived from it. Not fatal to events; fatal to speed (Step 5).
    if pixel_to_meter is None:
        limits.append("no_calibration")
        marginal = True
    elif spatial_confidence == "low":
        limits.append("weak_calibration")
        marginal = True

    if unsupported:
        profile, ceiling = PROFILE_UNSUPPORTED, CEILING_UNSUPPORTED
    elif marginal:
        profile, ceiling = PROFILE_MARGINAL, CEILING_MARGINAL
    else:
        profile, ceiling = PROFILE_SUPPORTED, CEILING_SUPPORTED

    return ConditionAssessment(profile=profile, confidence_ceiling=ceiling, limits=tuple(limits))
