"""Phase segmentation from pose alone (Pose-First MVP).

M09's segmenter already runs pose-only when M08 supplies no usable contact
(``bat_only_fallback``), but it lives in shot-service and picks its landmarks
from raw wrist-height extrema. Raw extrema are noise-sensitive: a single
jittery keypoint can move the "top of the backlift" several frames, and every
angle metric anchored to a phase inherits that error.

This is the same landmark model, differentiated properly:

    wrist midpoint -> Savitzky-Golay smooth -> vertical velocity + speed

- ``stance``          clip start; the settled address position.
- ``backlift``        hands first rise with sustained upward velocity.
- ``downswing``       vertical velocity reverses to downward at the top.
                      This is the X-Factor anchor (BM-04).
- ``impact``          peak hand speed after the downswing begins.
- ``follow_through``  speed decays below the quiet threshold, else clip end.

Thresholds are expressed in CIP frame-height units **per second**, so the same
constants behave identically at 30fps and 60fps (a 240fps clip must not detect
a different stroke). ``sustain_s`` likewise converts to a frame count from fps
rather than being a fixed number of frames.

Pure and deterministic (NFR-M10-03): no I/O, no randomness, no numpy. When the
motion is too sparse or too flat to find landmarks, the segmenter collapses the
boundaries and says so via :data:`PHASE_METHOD_POSE_INSUFFICIENT` rather than
inventing a plausible-looking timeline.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from biomechanics_service.domain.filters import savgol_smooth
from biomechanics_service.domain.stroke import Phases

#: Phase method recorded on the report when these boundaries were used. M10's
#: quality block surfaces it, so a consumer can tell a wrist-derived timeline
#: from a ball-anchored one.
PHASE_METHOD_POSE_WRIST = "pose_wrist_heuristic"
#: Recorded when the pose was too sparse/static to locate any landmark.
PHASE_METHOD_POSE_INSUFFICIENT = "pose_insufficient"

#: Fewest usable wrist samples before segmentation is meaningless.
MIN_SAMPLES = 5


@dataclass(frozen=True, slots=True)
class PhaseThresholds:
    """Frame-rate-independent detection thresholds.

    Velocities are CIP frame-height units per second. A batter's hands travel
    roughly one frame-height per second during a backlift, so the defaults sit
    an order of magnitude below that: sensitive enough for a gentle lift,
    high enough to ignore keypoint jitter.
    """

    #: Sustained upward velocity that counts as the backlift starting.
    lift_velocity: float = 0.12
    #: How long that velocity must persist (seconds) to reject single-frame spikes.
    sustain_s: float = 0.06
    #: Speed below which the follow-through is considered finished.
    quiet_speed: float = 0.15


DEFAULT_THRESHOLDS = PhaseThresholds()

#: One wrist-midpoint sample: (x, y) in the CIP frame, or None when the wrists
#: were not visible in that frame.
Sample = tuple[float, float] | None


def wrist_midpoints(
    frames: Sequence[tuple[float | None, float | None]],
) -> list[Sample]:
    """Per-frame midpoint of the two wrists, None where either is missing."""
    out: list[Sample] = []
    for left, right in frames:
        out.append(None if left is None or right is None else (left, right))
    return out


def _interpolate(samples: Sequence[Sample]) -> tuple[list[float], list[float], list[int]] | None:
    """Fill gaps by linear interpolation between the visible samples.

    Returns (xs, ys, source_frames) covering the span from the first to the
    last visible sample, or None when too few samples are visible. Smoothing
    and differencing need a continuous series; interpolating across a dropped
    frame is honest here because the gap is bounded by real observations.
    """
    visible = [(i, s) for i, s in enumerate(samples) if s is not None]
    if len(visible) < MIN_SAMPLES:
        return None

    first, last = visible[0][0], visible[-1][0]
    xs: list[float] = []
    ys: list[float] = []
    frames: list[int] = []
    for frame in range(first, last + 1):
        sample = samples[frame]
        if sample is not None:
            xs.append(sample[0])
            ys.append(sample[1])
        else:
            before = max(v for v in visible if v[0] < frame)
            after = min((v for v in visible if v[0] > frame), key=lambda v: v[0])
            span = after[0] - before[0]
            t = (frame - before[0]) / span if span else 0.0
            bx, by = before[1]
            ax, ay = after[1]
            xs.append(bx + (ax - bx) * t)
            ys.append(by + (ay - by) * t)
        frames.append(frame)
    return xs, ys, frames


def _velocities(xs: list[float], ys: list[float], *, fps: float) -> tuple[list[float], list[float]]:
    """(vertical velocity, speed) per sample, from SG-smoothed positions."""
    sx, sy = savgol_smooth(xs), savgol_smooth(ys)
    v_y: list[float] = []
    speed: list[float] = []
    for i in range(len(sy)):
        j = min(i + 1, len(sy) - 1)
        k = max(i - 1, 0)
        steps = j - k
        if steps == 0:
            v_y.append(0.0)
            speed.append(0.0)
            continue
        dy = (sy[j] - sy[k]) / steps * fps
        dx = (sx[j] - sx[k]) / steps * fps
        v_y.append(dy)
        speed.append(math.hypot(dx, dy))
    return v_y, speed


def segment_phases_from_pose(
    samples: Sequence[Sample],
    *,
    fps: float,
    frame_count: int,
    thresholds: PhaseThresholds = DEFAULT_THRESHOLDS,
) -> Phases:
    """Locate the five phase boundaries from wrist motion alone.

    ``samples`` is indexed by frame. Boundaries are returned as frame indices
    into the original clip, forced non-decreasing — a stroke cannot run its
    phases out of order.
    """
    last = max(frame_count - 1, 0)
    rate = fps if fps > 0 else 30.0

    prepared = _interpolate(samples)
    if prepared is None:
        return Phases(0, 0, 0, 0, 0, method=PHASE_METHOD_POSE_INSUFFICIENT)
    xs, ys, frames = prepared

    v_y, speed = _velocities(xs, ys, fps=rate)
    sustain = max(1, round(thresholds.sustain_s * rate))

    # --- backlift: first sustained upward run -------------------------------
    backlift_pos: int | None = None
    for i in range(len(v_y) - sustain + 1):
        if all(v_y[i + k] >= thresholds.lift_velocity for k in range(sustain)):
            backlift_pos = i
            break

    # --- top of backlift: highest hands at or after the lift ----------------
    search_from = backlift_pos if backlift_pos is not None else 0
    top_pos = max(range(search_from, len(ys)), key=lambda i: ys[i])

    # The downswing begins where upward motion turns over. Prefer the first
    # frame at/after the top whose velocity has actually gone negative; fall
    # back to the top itself when the turnover is too gentle to register.
    downswing_pos = top_pos
    for i in range(top_pos, len(v_y)):
        if v_y[i] < 0:
            downswing_pos = i
            break

    if backlift_pos is None:
        # No detectable lift: treat the whole approach as stance up to the top.
        backlift_pos = top_pos

    # --- impact: fastest hands after the downswing starts -------------------
    after = range(downswing_pos, len(speed))
    impact_pos = max(after, key=lambda i: speed[i]) if len(speed) > downswing_pos else downswing_pos

    # --- follow-through: hands go quiet, else the clip ends ------------------
    follow_pos = len(speed) - 1
    for i in range(impact_pos + 1, len(speed)):
        if speed[i] < thresholds.quiet_speed:
            follow_pos = i
            break

    ordered = _clamp_monotonic(
        0,
        frames[backlift_pos],
        frames[downswing_pos],
        frames[impact_pos],
        frames[follow_pos],
        last=last,
    )
    stance, backlift, downswing, impact, follow = ordered
    return Phases(
        stance=stance,
        backlift=backlift,
        downswing=downswing,
        impact=impact,
        follow_through=follow,
        method=PHASE_METHOD_POSE_WRIST,
    )


def _clamp_monotonic(*boundaries: int, last: int) -> tuple[int, ...]:
    """Force a non-decreasing, in-range sequence (mirrors M09's guarantee)."""
    result: list[int] = []
    current = 0
    for b in boundaries:
        current = max(current, min(max(b, 0), last))
        result.append(current)
    return tuple(result)
