"""Speed estimation — ESTIMATED, always (M08 Step 5, FR-M08-04, AC-M08-03).

The arithmetic is simple: displacement in pixels, times metres per pixel from
M05's calibration, times frames per second. Everything difficult about this
module is in deciding when NOT to answer, and in never letting the answer lose
its label.

Why the label is structural rather than a convention: :class:`SpeedEstimate`
carries ``provenance = estimated`` as a field, so speed cannot be passed around
as a bare float that silently becomes "measured" in a UI three modules later.
Book 4 Ch. 4 requires the class; making it un-droppable is how the requirement
survives contact with real code.

What limits an estimate, all recorded in ``limited_by`` so the number is never
presented without its caveats:

- **No calibration.** Without metres-per-pixel there is no speed at all, only
  pixels per second, which is not a physical quantity anyone can coach from.
  Refused outright rather than reported in arbitrary units.
- **Low frame rate.** At 30fps a 140km/h ball moves ~1.3m between frames, so
  the displacement is a coarse average over a long interval. The estimate is
  produced but its confidence drops.
- **Short track.** Two points give one interval and no way to tell a good
  measurement from an outlier. More intervals mean more agreement to check.
- **Depth.** A monocular camera cannot see motion toward or away from it, so a
  ball angled across the frame reads slower than it is. M05 already tells us
  ``depth_estimated`` is always true for phone footage; the ceiling here
  reflects that this is a floor on true speed, not a two-sided measurement.

The measured segment deliberately ends at the bounce when one was detected: the
ball loses speed on contact with the pitch, so averaging across the bounce
mixes two different speeds and reports neither. Pre-bounce flight is what
"delivery speed" means.
"""

from __future__ import annotations

import itertools
import math
import statistics
from dataclasses import dataclass

from ball_service.domain.ball import BallEvent, BallPosition, SpeedEstimate
from ball_service.domain.detection import BallTrack

#: Below this frame rate the inter-frame interval is too coarse for a
#: trustworthy estimate — still reported, but capped.
FPS_TRUSTWORTHY = 50.0

#: Intervals needed before inter-interval agreement means anything.
MIN_INTERVALS = 2

#: A monocular camera cannot resolve motion along its own axis, so no
#: single-camera speed can be fully trusted (Book 4 Ch. 2 §2.3).
MONOCULAR_CEILING = 0.75

#: Confidence multipliers for the named limits.
LOW_FPS_FACTOR = 0.6
SHORT_TRACK_FACTOR = 0.7
WEAK_CALIBRATION_FACTOR = 0.6
#: How much disagreement between intervals is tolerated before confidence
#: falls: coefficient of variation at or above this halves it.
CV_TOLERANCE = 0.35


@dataclass(frozen=True, slots=True)
class _Segment:
    positions: tuple[BallPosition, ...]
    ended_at_bounce: bool


def _measured_segment(track: BallTrack, bounce: BallEvent | None) -> _Segment:
    """The pre-bounce flight, which is what 'delivery speed' means."""
    if bounce is None:
        return _Segment(positions=track.positions, ended_at_bounce=False)
    before = tuple(p for p in track.positions if p.frame_index <= bounce.frame_index)
    if len(before) < 2:
        # The bounce is at the very start of what we saw; use the whole track
        # rather than refusing, and let the short-track penalty apply.
        return _Segment(positions=track.positions, ended_at_bounce=False)
    return _Segment(positions=before, ended_at_bounce=True)


def estimate_speed(
    track: BallTrack,
    *,
    bounce: BallEvent | None,
    fps: float | None,
    pixel_to_meter: float | None,
    frame_height: int,
    spatial_confidence: str | None = None,
) -> SpeedEstimate | None:
    """Estimate delivery speed, or return None when it cannot be estimated.

    ``pixel_to_meter`` is metres per pixel from M05. Track coordinates are in
    frame-height units, so they are scaled back to pixels before conversion —
    the two must agree or the answer is wrong by a factor of a thousand.
    """
    if fps is None or fps <= 0:
        return None
    if pixel_to_meter is None or pixel_to_meter <= 0:
        # Pixels per second is not a speed anyone can coach from.
        return None

    segment = _measured_segment(track, bounce)
    positions = segment.positions
    if len(positions) < 2:
        return None

    scale = float(frame_height) if frame_height else 1.0
    speeds: list[float] = []
    for a, b in itertools.pairwise(positions):
        frames_apart = b.frame_index - a.frame_index
        if frames_apart <= 0:
            continue
        pixels = math.hypot(b.x - a.x, b.y - a.y) * scale
        metres = pixels * pixel_to_meter
        seconds = frames_apart / fps
        if seconds > 0:
            speeds.append(metres / seconds)
    if not speeds:
        return None

    limits: list[str] = []
    confidence = track.mean_confidence

    # A monocular camera cannot see motion along its own axis, so this is a
    # lower bound on true speed rather than a symmetric measurement.
    confidence *= MONOCULAR_CEILING
    limits.append("monocular_depth")

    if fps < FPS_TRUSTWORTHY:
        confidence *= LOW_FPS_FACTOR
        limits.append("low_fps")

    if len(speeds) < MIN_INTERVALS:
        confidence *= SHORT_TRACK_FACTOR
        limits.append("short_track")

    if spatial_confidence in {"low", "medium"}:
        confidence *= WEAK_CALIBRATION_FACTOR
        limits.append("weak_calibration")

    # Disagreement between intervals is the estimate's own error signal — no
    # golden data needed to notice that the measurements do not agree.
    mean_speed = statistics.fmean(speeds)
    if len(speeds) >= MIN_INTERVALS and mean_speed > 0:
        cv = statistics.pstdev(speeds) / mean_speed
        if cv >= CV_TOLERANCE:
            confidence *= 0.5
            limits.append("inconsistent_intervals")

    if not segment.ended_at_bounce and bounce is not None:
        limits.append("bounce_not_excluded")

    return SpeedEstimate(
        metres_per_second=mean_speed,
        confidence=max(0.0, min(1.0, confidence)),
        limited_by=tuple(limits),
    )
