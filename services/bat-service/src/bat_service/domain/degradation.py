"""Confidence aggregation + the degradation policy (M07 Step 6, FR-M07-05).

The rule from the spec: when detection fails on more than 30% of DOWNSWING
frames, the bat-dependent output is marked provisional, which M10 honours.

Why the downswing specifically, and not the whole clip: a bat that vanishes
during the follow-through costs almost nothing — the metrics that matter
(backlift, bat path, bat lag, impact) are already computed by then. A bat that
vanishes on the way down costs everything. Averaging failures over the clip
would let a clean follow-through hide exactly the failures that damage the
result.

The spec names the downswing but does not define its bounds, so M07 defines
them from the bat's own motion: from the top of the backlift (highest blade
tip in the CIP frame, Y up) to the lowest point that follows it (impact or
the bottom of the arc). That is self-contained — no shot-recognition
dependency on M09, which does not exist yet and which would invert the
pipeline's direction anyway.

When the window cannot be established (too little detection to see the arc),
the policy falls back to the whole clip. Falling back to a WIDER window is the
safe direction: it can only make the output more cautious, never less.
"""

from __future__ import annotations

from dataclasses import dataclass

from bat_service.domain.bat import (
    BLADE_TIP,
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    BatFrame,
)

#: More than this fraction of downswing frames failing makes output provisional.
MAX_DOWNSWING_FAILURE_RATIO = 0.30

#: A track this weak is provisional even if every frame "detected" something —
#: consistently marginal detections are not a trustworthy bat path.
MIN_MEAN_CONFIDENCE = 0.45

#: Below this many detected frames there is no usable bat track at all.
MIN_DETECTED_FRAMES = 2


@dataclass(frozen=True, slots=True)
class DownswingWindow:
    """Inclusive frame-index bounds of the downswing, and how it was found."""

    start: int
    end: int
    #: motion (derived from the bat's arc) | whole_clip (fallback)
    basis: str

    @property
    def length(self) -> int:
        return self.end - self.start + 1


@dataclass(frozen=True, slots=True)
class DegradationResult:
    mean_confidence: float
    frames_detected: int
    downswing: DownswingWindow
    downswing_failures: int
    downswing_failure_ratio: float
    provisional: bool
    quality: str
    #: Stable slug explaining a provisional/rejected verdict; None when ok.
    reason: str | None


def find_downswing(frames: tuple[BatFrame, ...]) -> DownswingWindow:
    """Bound the downswing from the bat's own motion: backlift top -> lowest point."""
    whole = DownswingWindow(
        start=frames[0].frame_index if frames else 0,
        end=frames[-1].frame_index if frames else 0,
        basis="whole_clip",
    )
    tips = [
        (f.frame_index, tip.y)
        for f in frames
        if f.detected and (tip := f.part(BLADE_TIP)) is not None
    ]
    if len(tips) < 2:
        return whole

    # Top of the backlift: highest blade tip (CIP frame is Y-up).
    top_position = max(range(len(tips)), key=lambda i: tips[i][1])
    after = tips[top_position:]
    if len(after) < 2:
        # The highest point is the last thing seen — no downswing observed.
        return whole

    bottom_offset = min(range(len(after)), key=lambda i: after[i][1])
    start, end = after[0][0], after[bottom_offset][0]

    # If nothing is detected after the lowest point, the track did not end —
    # we LOST it, and losing the bat at impact is the most damaging failure
    # there is. Extend the window to the end of the clip so those frames are
    # counted. When later detections exist, the bat came back on the
    # follow-through and the window legitimately closes at the bottom.
    if end == after[-1][0] and frames and frames[-1].frame_index > end:
        end = frames[-1].frame_index

    if end <= start:
        return whole
    return DownswingWindow(start=start, end=end, basis="motion")


def assess(frames: tuple[BatFrame, ...]) -> DegradationResult:
    """Aggregate confidence and apply the degradation policy to a bat track."""
    detected = [f for f in frames if f.detected]
    mean_confidence = sum(f.confidence for f in detected) / len(detected) if detected else 0.0

    window = find_downswing(frames)
    in_window = [f for f in frames if window.start <= f.frame_index <= window.end]
    failures = sum(1 for f in in_window if not f.detected)
    # An empty window would make the ratio undefined; treat it as total failure,
    # since we then have no downswing evidence at all.
    ratio = failures / len(in_window) if in_window else 1.0

    if len(detected) < MIN_DETECTED_FRAMES:
        return DegradationResult(
            mean_confidence=mean_confidence,
            frames_detected=len(detected),
            downswing=window,
            downswing_failures=failures,
            downswing_failure_ratio=ratio,
            provisional=True,
            quality=QUALITY_REJECTED,
            reason="no_bat_detected",
        )

    if ratio > MAX_DOWNSWING_FAILURE_RATIO:
        return DegradationResult(
            mean_confidence=mean_confidence,
            frames_detected=len(detected),
            downswing=window,
            downswing_failures=failures,
            downswing_failure_ratio=ratio,
            provisional=True,
            quality=QUALITY_PROVISIONAL,
            reason="downswing_detection_gaps",
        )

    if mean_confidence < MIN_MEAN_CONFIDENCE:
        return DegradationResult(
            mean_confidence=mean_confidence,
            frames_detected=len(detected),
            downswing=window,
            downswing_failures=failures,
            downswing_failure_ratio=ratio,
            provisional=True,
            quality=QUALITY_PROVISIONAL,
            reason="low_detection_confidence",
        )

    return DegradationResult(
        mean_confidence=mean_confidence,
        frames_detected=len(detected),
        downswing=window,
        downswing_failures=failures,
        downswing_failure_ratio=ratio,
        provisional=False,
        quality=QUALITY_OK,
        reason=None,
    )
