"""Golden-dataset validation gate for the ball tracker (M08 Step 8, ENG-007).

A tracker change must not ship if it regresses event accuracy or speed error
beyond target on the supported condition profile (AC-M08-07, NFR-M08-06).

M08's gate has a hazard the pose and bat gates do not, and it comes directly
from this module's own design. M08 is allowed — required, even — to report
nothing when it is unsure. A tracker that became uniformly unsure would
therefore emit no wrong events at all and score a *perfect* error rate on
whatever it still emitted. The fail-safe would have become a way to pass the
gate.

So the gate scores three things, and a regression in any one blocks:

- **Event accuracy** — detected events must land within
  :data:`FRAME_TOLERANCE` of truth. A missing event counts as a miss, not as
  an abstention.
- **Event recall** — the fraction of true events actually reported must hold
  up. This is the anti-silence check: it is what a suppress-everything tracker
  fails.
- **Speed error** — mean absolute error against known truth, as a fraction.

The golden corpus itself does not exist: real ground truth for ball events
needs high-speed reference footage under the supported condition profile. The
gate is built and tested against reference snapshots and starts blocking on
real data the moment it lands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ball_service.domain.ball import BallEvent, BallEvents
from ball_service.domain.pipeline import compute_ball_run
from ball_service.domain.tracker import BallTracker

#: A detected event this many frames from truth or closer counts as correct.
FRAME_TOLERANCE = 2

#: Max acceptable mean absolute speed error, as a fraction of true speed.
DEFAULT_SPEED_TOLERANCE = 0.15

#: Min fraction of true events the tracker must actually report. The check that
#: stops silence from scoring as accuracy.
DEFAULT_MIN_RECALL = 0.70


@dataclass(frozen=True, slots=True)
class GoldenDelivery:
    """One golden clip: capture parameters plus known truth."""

    name: str
    frame_count: int
    width: int
    height: int
    fps: float
    pixel_to_meter: float | None = None
    spatial_confidence: str | None = "high"
    camera_angle: str | None = "side_on"
    quality_flags: list[dict[str, Any]] | None = None
    #: Truth. Absent keys mean the event genuinely does not occur in this clip.
    true_release: int | None = None
    true_bounce: int | None = None
    true_contact: int | None = None
    true_speed_mps: float | None = None


@dataclass(frozen=True, slots=True)
class ValidationReport:
    #: Fraction of REPORTED events that were within tolerance.
    event_accuracy: float
    #: Fraction of TRUE events that were reported at all.
    event_recall: float
    #: Mean absolute speed error as a fraction of truth; inf when unmeasurable.
    speed_error: float
    per_delivery: dict[str, str]
    passed: bool
    reason: str | None


def _reported(events: BallEvents) -> dict[str, BallEvent]:
    return {
        kind: event
        for kind, event in (
            ("release", events.release),
            ("bounce", events.bounce),
            ("contact", events.contact),
        )
        if event is not None
    }


def _truth(sample: GoldenDelivery) -> dict[str, int]:
    return {
        kind: frame
        for kind, frame in (
            ("release", sample.true_release),
            ("bounce", sample.true_bounce),
            ("contact", sample.true_contact),
        )
        if frame is not None
    }


def run_validation(
    tracker: BallTracker,
    golden: list[GoldenDelivery],
    *,
    frame_tolerance: int = FRAME_TOLERANCE,
    speed_tolerance: float = DEFAULT_SPEED_TOLERANCE,
    min_recall: float = DEFAULT_MIN_RECALL,
) -> ValidationReport:
    """Score a candidate tracker against the golden set. Blocks on regression."""
    if not golden:
        # An empty corpus proves nothing, so it must not read as a pass.
        return ValidationReport(
            event_accuracy=0.0,
            event_recall=0.0,
            speed_error=math.inf,
            per_delivery={},
            passed=False,
            reason="empty_golden_set",
        )

    correct = 0
    reported_total = 0
    truth_total = 0
    speed_errors: list[float] = []
    per_delivery: dict[str, str] = {}

    for sample in golden:
        result = compute_ball_run(
            tracker,
            frame_count=sample.frame_count,
            width=sample.width,
            height=sample.height,
            fps=sample.fps,
            pixel_to_meter=sample.pixel_to_meter,
            spatial_confidence=sample.spatial_confidence,
            camera_angle=sample.camera_angle,
            quality_flags=sample.quality_flags,
        )
        reported = _reported(result.events)
        truth = _truth(sample)

        hits = 0
        for kind, true_frame in truth.items():
            event = reported.get(kind)
            if event is not None and abs(event.frame_index - true_frame) <= frame_tolerance:
                hits += 1
        correct += hits
        reported_total += len(reported)
        truth_total += len(truth)
        per_delivery[sample.name] = f"{hits}/{len(truth)} events"

        if sample.true_speed_mps and result.events.speed is not None:
            speed_errors.append(
                abs(result.events.speed.metres_per_second - sample.true_speed_mps)
                / sample.true_speed_mps
            )

    event_accuracy = (correct / reported_total) if reported_total else 0.0
    event_recall = (correct / truth_total) if truth_total else 0.0
    speed_error = (sum(speed_errors) / len(speed_errors)) if speed_errors else math.inf

    failures: list[str] = []
    if event_recall < min_recall:
        # The anti-silence check: a tracker that stopped reporting would sail
        # through an accuracy-only gate.
        failures.append("event_recall")
    if reported_total and event_accuracy < min_recall:
        failures.append("event_accuracy")
    if speed_errors and speed_error > speed_tolerance:
        failures.append("speed_error")

    return ValidationReport(
        event_accuracy=event_accuracy,
        event_recall=event_recall,
        speed_error=speed_error,
        per_delivery=per_delivery,
        passed=not failures,
        reason="+".join(failures) if failures else None,
    )


def build_golden_from_reference(
    tracker: BallTracker,
    specs: list[tuple[str, int, int, int, float]],
    *,
    pixel_to_meter: float = 0.004,
) -> list[GoldenDelivery]:
    """Snapshot a reference tracker's output as truth, for gate tests.

    Real golden data is high-speed reference footage. This exists so the gate's
    own behaviour is testable today: a candidate is compared against a frozen
    snapshot of the reference, which is exactly the regression check CI runs
    once real ground truth replaces the snapshot.
    """
    samples: list[GoldenDelivery] = []
    for name, frame_count, width, height, fps in specs:
        result = compute_ball_run(
            tracker,
            frame_count=frame_count,
            width=width,
            height=height,
            fps=fps,
            pixel_to_meter=pixel_to_meter,
            spatial_confidence="high",
            camera_angle="side_on",
        )
        events = result.events
        samples.append(
            GoldenDelivery(
                name=name,
                frame_count=frame_count,
                width=width,
                height=height,
                fps=fps,
                pixel_to_meter=pixel_to_meter,
                true_release=events.release.frame_index if events.release else None,
                true_bounce=events.bounce.frame_index if events.bounce else None,
                true_contact=events.contact.frame_index if events.contact else None,
                true_speed_mps=(events.speed.metres_per_second if events.speed else None),
            )
        )
    return samples
