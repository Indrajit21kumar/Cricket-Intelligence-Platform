"""Golden-dataset validation gate for the bat detector (M07 Step 8, ENG-007).

A detector change MUST NOT ship if it regresses bat-detection accuracy beyond
target (AC-M07-06, NFR-M07-05). This module is the mechanism: run the
candidate detector over the golden clips, measure error against ground truth,
and block if it exceeds tolerance.

M07's gate measures two things where M06's measured one, because a bat
detector can fail in two independent ways:

- **Localisation error** — the parts are found, but in the wrong place.
- **Detection rate** — the bat is not found at all. A detector that quietly
  stops detecting would score a *better* mean error than one that detects
  everything slightly imprecisely, since only the frames it did emit get
  measured. Gating on error alone would let that ship, so a minimum detection
  rate is enforced alongside it.

The golden corpus itself is a data workstream that does not exist yet (M07 is
data-gated by design, §2). The gate that will consume it is built and tested
here against fixture samples, and is wired into CI so it starts blocking the
moment real golden data lands.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bat_service.domain.bat import BatFrame, BatPart
from bat_service.domain.detector import BatDetector
from bat_service.domain.pipeline import compute_bat_run
from bat_service.domain.pose_client import PoseTrack

#: Max acceptable mean part-localisation error, in CIP units (fractions of
#: frame height). Tighten as the golden set and detectors mature.
DEFAULT_TOLERANCE = 0.05

#: Min fraction of golden frames in which the bat must be found at all. A
#: detector that stops detecting must not pass by being precise on the few
#: frames it kept.
DEFAULT_MIN_DETECTION_RATE = 0.80


@dataclass(frozen=True, slots=True)
class GoldenSample:
    """One golden clip: frame geometry, pose, and ground-truth bat parts."""

    name: str
    frame_count: int
    width: int
    height: int
    pose: PoseTrack | None
    #: Ground-truth parts per frame, in the same frame the pipeline emits.
    truth_frames: tuple[tuple[BatPart, ...], ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    mean_error: float
    detection_rate: float
    per_sample: dict[str, float]
    passed: bool
    tolerance: float
    min_detection_rate: float
    #: Why a failing report failed — localisation | detection_rate | both.
    reason: str | None


def _frame_error(pred: tuple[BatPart, ...], truth: tuple[BatPart, ...]) -> float | None:
    """Mean Euclidean distance over parts present in both frames."""
    truth_by_part = {p.part: p for p in truth}
    distances: list[float] = []
    for p in pred:
        t = truth_by_part.get(p.part)
        if t is not None:
            distances.append(math.hypot(p.x - t.x, p.y - t.y))
    if not distances:
        return None
    return sum(distances) / len(distances)


def sample_error(frames: tuple[BatFrame, ...], sample: GoldenSample) -> float:
    """Mean localisation error over comparable frames; inf when none compare."""
    errors: list[float] = []
    for frame in frames:
        if not frame.detected or frame.frame_index >= len(sample.truth_frames):
            continue
        error = _frame_error(frame.parts, sample.truth_frames[frame.frame_index])
        if error is not None:
            errors.append(error)
    if not errors:
        # Nothing comparable: treat as maximally wrong rather than as a pass.
        return math.inf
    return sum(errors) / len(errors)


def run_validation(
    detector: BatDetector,
    golden: list[GoldenSample],
    *,
    tolerance: float = DEFAULT_TOLERANCE,
    min_detection_rate: float = DEFAULT_MIN_DETECTION_RATE,
) -> ValidationReport:
    """Score a candidate detector against the golden set. Blocks on regression."""
    if not golden:
        # An empty corpus proves nothing, so it must not read as a pass.
        return ValidationReport(
            mean_error=math.inf,
            detection_rate=0.0,
            per_sample={},
            passed=False,
            tolerance=tolerance,
            min_detection_rate=min_detection_rate,
            reason="empty_golden_set",
        )

    per_sample: dict[str, float] = {}
    detected_total = 0
    frames_total = 0
    for sample in golden:
        result = compute_bat_run(
            detector,
            frame_count=sample.frame_count,
            width=sample.width,
            height=sample.height,
            pose=sample.pose,
        )
        per_sample[sample.name] = sample_error(result.frames, sample)
        detected_total += result.degradation.frames_detected
        frames_total += sample.frame_count

    mean_error = sum(per_sample.values()) / len(per_sample)
    detection_rate = detected_total / frames_total if frames_total else 0.0

    localisation_failed = mean_error > tolerance
    detection_failed = detection_rate < min_detection_rate
    reason = None
    if localisation_failed and detection_failed:
        reason = "both"
    elif localisation_failed:
        reason = "localisation"
    elif detection_failed:
        reason = "detection_rate"

    return ValidationReport(
        mean_error=mean_error,
        detection_rate=detection_rate,
        per_sample=per_sample,
        passed=reason is None,
        tolerance=tolerance,
        min_detection_rate=min_detection_rate,
        reason=reason,
    )


def build_golden_from_reference(
    detector: BatDetector,
    geometries: list[tuple[str, int, int, int]],
    *,
    pose: PoseTrack | None = None,
) -> list[GoldenSample]:
    """Snapshot a reference detector's output as ground truth, for gate tests.

    Real golden data is mocap/human-labelled. This exists so the gate's own
    behaviour is testable today: a detector is compared against a frozen
    snapshot of the reference, which is exactly the regression check CI runs
    once real ground truth replaces the snapshot.
    """
    samples: list[GoldenSample] = []
    for name, frame_count, width, height in geometries:
        result = compute_bat_run(
            detector, frame_count=frame_count, width=width, height=height, pose=pose
        )
        truth = tuple(frame.parts if frame.detected else () for frame in result.frames)
        samples.append(
            GoldenSample(
                name=name,
                frame_count=frame_count,
                width=width,
                height=height,
                pose=pose,
                truth_frames=truth,
            )
        )
    return samples
