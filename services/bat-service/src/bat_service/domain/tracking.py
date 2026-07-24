"""Bat tracking + hand-bat association (M07 Step 4, FR-M07-04, AC-M07-02).

A net contains more than one bat. Picking the wrong one poisons every bat
metric downstream, and — unlike M06's multi-subject case — there is usually a
decisive signal available: the batter is *holding* their bat, so its handle is
at their hands. M06 tells us where those hands are.

Selection, in order of preference:

1. **Hands.** With wrists for the frame, choose the bat whose handle is
   nearest the wrist midpoint, provided it is within
   :data:`MAX_HAND_DISTANCE` — a bat further than that is not being held by
   this batter, however confident the detector is.
2. **Continuity.** Without wrists for a frame (occlusion, a dropped pose
   frame), stay with the bat nearest the previous frame's handle. A bat does
   not teleport between frames, so continuity is a real signal rather than a
   fallback guess.
3. **Nothing.** If neither applies, the frame is undetected. M07 does not fall
   back to "the most confident bat" — that is precisely how the net partner's
   bat gets tracked, and a missing frame is honest where a wrong one is not.

All distances are in CIP units (fractions of frame height), so thresholds mean
the same thing at any resolution.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bat_service.domain.bat import (
    HANDLE_BOTTOM,
    BatDetection,
    BatFrame,
    BatPart,
    FrameDetections,
)
from bat_service.domain.parts import detection_confidence, with_derived_parts
from bat_service.domain.pose_client import CipFrame, PoseTrack

#: Farthest a held bat's handle can sit from the wrist midpoint, in CIP units
#: (~15% of frame height). Beyond this it belongs to somebody else.
MAX_HAND_DISTANCE = 0.15

#: Farthest a bat may move between consecutive frames and still be the same
#: bat. Generous, because a bat genuinely moves fast through a stroke.
MAX_CONTINUITY_DISTANCE = 0.35

# How the bat in a frame was chosen — carried for observability, since a run
# tracked mostly by continuity is weaker evidence than one tracked by hands.
ASSOCIATION_HANDS = "hands"
ASSOCIATION_CONTINUITY = "continuity"
ASSOCIATION_NONE = "none"


@dataclass(frozen=True, slots=True)
class TrackingResult:
    frames: tuple[BatFrame, ...]
    #: Per-frame association method, aligned 1:1 with ``frames``.
    associations: tuple[str, ...]

    @property
    def frames_detected(self) -> int:
        return sum(1 for f in self.frames if f.detected)


def _distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _to_cip(part: BatPart, frame: CipFrame) -> BatPart:
    x, y = frame.to_cip(part.x, part.y)
    return BatPart(
        part=part.part,
        x=x,
        y=y,
        confidence=part.confidence,
        provenance=part.provenance,
    )


def _detection_in_cip(detection: BatDetection, frame: CipFrame) -> BatDetection:
    return BatDetection(
        parts=tuple(_to_cip(p, frame) for p in detection.parts),
        score=detection.score,
    )


def _handle_position(detection: BatDetection) -> tuple[float, float] | None:
    handle = detection.part(HANDLE_BOTTOM)
    return (handle.x, handle.y) if handle is not None else None


def track_bat(
    detections: list[FrameDetections],
    *,
    pose: PoseTrack | None,
    cip_frame: CipFrame | None = None,
) -> TrackingResult:
    """Follow one bat — the batter's — across the clip.

    ``pose`` supplies the wrists and, normally, the CIP frame. ``cip_frame``
    overrides it for the case where pose is missing entirely but the frame is
    known from elsewhere; without either, coordinates stay as the detector
    produced them.
    """
    frame_def = cip_frame or (pose.frame if pose is not None else None)
    identity = CipFrame(origin_x=0.0, origin_y=0.0, scale=1.0)
    transform = frame_def or identity

    out: list[BatFrame] = []
    associations: list[str] = []
    previous_handle: tuple[float, float] | None = None

    for detected in detections:
        candidates = [_detection_in_cip(d, transform) for d in detected.bats]
        if not candidates:
            out.append(BatFrame(frame_index=detected.frame_index, detected=False))
            associations.append(ASSOCIATION_NONE)
            # A gap does not reset continuity: the bat is still where it was.
            continue

        chosen: BatDetection | None = None
        method = ASSOCIATION_NONE

        wrists = pose.at(detected.frame_index) if pose is not None else None
        hands = wrists.midpoint if wrists is not None else None
        if hands is not None:
            best: tuple[float, BatDetection] | None = None
            for candidate in candidates:
                handle = _handle_position(candidate)
                if handle is None:
                    continue
                distance = _distance(handle, hands)
                if best is None or distance < best[0]:
                    best = (distance, candidate)
            if best is not None and best[0] <= MAX_HAND_DISTANCE:
                chosen, method = best[1], ASSOCIATION_HANDS

        if chosen is None and previous_handle is not None:
            best = None
            for candidate in candidates:
                handle = _handle_position(candidate)
                if handle is None:
                    continue
                distance = _distance(handle, previous_handle)
                if best is None or distance < best[0]:
                    best = (distance, candidate)
            if best is not None and best[0] <= MAX_CONTINUITY_DISTANCE:
                chosen, method = best[1], ASSOCIATION_CONTINUITY

        if chosen is None:
            # Deliberately NOT "take the most confident bat" — that is how the
            # wrong player's bat gets tracked for a whole clip.
            out.append(BatFrame(frame_index=detected.frame_index, detected=False))
            associations.append(ASSOCIATION_NONE)
            continue

        enriched = with_derived_parts(chosen)
        out.append(
            BatFrame(
                frame_index=detected.frame_index,
                detected=True,
                parts=enriched.parts,
                confidence=detection_confidence(enriched),
            )
        )
        associations.append(method)
        previous_handle = _handle_position(chosen) or previous_handle

    return TrackingResult(frames=tuple(out), associations=tuple(associations))
