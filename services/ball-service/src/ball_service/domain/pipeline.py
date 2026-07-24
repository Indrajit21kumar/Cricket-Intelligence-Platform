"""Ball compute pipeline (M08 Steps 2-6 orchestration).

One pure function, so the whole delivery can be reasoned about and tested with
no DB, GPU or broker:

    capture-condition gate -> detect (motion) -> events -> line/length
    -> speed -> fail-safe

The order is the argument. Conditions are assessed FIRST so their ceiling binds
everything after them; the fail-safe runs LAST so it can suppress a result that
individual stages were each locally happy with. Step 7 wraps this with I/O and
adds no decisions of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ball_service.domain.ball import BallEvents
from ball_service.domain.bat_client import BatTrack
from ball_service.domain.conditions import ConditionAssessment, assess_conditions
from ball_service.domain.detection import BallTrack, build_track
from ball_service.domain.events import (
    StumpReference,
    classify_length,
    classify_line,
    detect_bounce,
    detect_contact,
    detect_release,
)
from ball_service.domain.failsafe import FailSafeResult, apply_failsafe
from ball_service.domain.speed import estimate_speed
from ball_service.domain.tracker import BallTracker


@dataclass(frozen=True, slots=True)
class BallRunResult:
    model_version: str
    dataset_version: str | None
    frame_count: int
    track: BallTrack
    conditions: ConditionAssessment
    failsafe: FailSafeResult

    @property
    def events(self) -> BallEvents:
        return self.failsafe.events

    @property
    def frames_detected(self) -> int:
        return self.track.frames_detected


def compute_ball_run(
    tracker: BallTracker,
    *,
    frame_count: int,
    width: int,
    height: int,
    fps: float | None,
    pixel_to_meter: float | None = None,
    spatial_confidence: str | None = None,
    camera_angle: str | None = None,
    quality_flags: list[dict[str, Any]] | None = None,
    stumps: StumpReference | None = None,
    bat: BatTrack | None = None,
) -> BallRunResult:
    """Run the full ball pipeline over a clip."""
    conditions = assess_conditions(
        fps=fps,
        quality_flags=quality_flags,
        pixel_to_meter=pixel_to_meter,
        spatial_confidence=spatial_confidence,
    )

    # Detection still runs on unsupported clips rather than short-circuiting:
    # the fail-safe needs to distinguish "conditions too poor" from "conditions
    # poor AND nothing there", and the run is cheap enough that the clarity is
    # worth more than the saved cycles.
    candidates = tracker.detect(frame_count=frame_count, width=width, height=height)
    track = build_track(candidates, height=height)

    frame_width = (width / height) if height else 1.0
    release = detect_release(track, frame_width=frame_width)
    bounce = detect_bounce(track)
    # A bat track that is not in the same frame as the ball is worse than none.
    contact = detect_contact(
        track, bat_positions=bat.positions if (bat is not None and bat.usable) else None
    )
    line, line_confidence = classify_line(bounce, track, stumps=stumps, camera_angle=camera_angle)
    length, length_confidence = classify_length(
        bounce, track, stumps=stumps, camera_angle=camera_angle
    )
    speed = estimate_speed(
        track,
        bounce=bounce,
        fps=fps,
        pixel_to_meter=pixel_to_meter,
        frame_height=height,
        spatial_confidence=spatial_confidence,
    )

    candidate_events = BallEvents(
        release=release,
        bounce=bounce,
        contact=contact,
        line=line,
        line_confidence=line_confidence,
        length=length,
        length_confidence=length_confidence,
        speed=speed,
    )

    failsafe = apply_failsafe(
        candidate_events,
        track=track,
        conditions=conditions,
        frame_count=frame_count,
    )

    return BallRunResult(
        model_version=tracker.version,
        dataset_version=tracker.dataset_version,
        frame_count=frame_count,
        track=track,
        conditions=conditions,
        failsafe=failsafe,
    )
