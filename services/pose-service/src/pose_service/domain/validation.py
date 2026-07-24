"""Golden-dataset validation gate (M06 Step 7, ENG-007, AC-M06-06).

A model change (or a new model) MUST NOT ship if it regresses keypoint
accuracy beyond tolerance against the golden dataset (mocap-derived ground
truth). This module is the *mechanism*: run the candidate model over the
golden clips, measure per-keypoint error against the truth, and block if the
mean error exceeds the tolerance. The real golden set (labelled + mocap
validated) is a data workstream (Book 7 §4); the gate that consumes it is
built and tested here with fixture samples.

Wire ``run_validation`` into CI before a model version is promoted: a failing
report fails the build, so a regressed model is blocked automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pose_service.domain.keypoints import Keypoint
from pose_service.domain.model import PoseModel
from pose_service.domain.pipeline import compute_pose_run

# Max acceptable mean per-keypoint error (in normalised-frame units) for a
# model to pass the gate. Tighten as the golden set + models mature.
DEFAULT_TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class GoldenSample:
    """One golden clip: frame geometry + ground-truth normalised keypoints."""

    name: str
    frame_count: int
    width: int
    height: int
    truth_frames: tuple[tuple[Keypoint, ...], ...]


@dataclass(frozen=True, slots=True)
class ValidationReport:
    mean_error: float
    per_sample: dict[str, float]
    passed: bool
    tolerance: float


def _frame_error(pred: tuple[Keypoint, ...], truth: tuple[Keypoint, ...]) -> float | None:
    """Mean Euclidean distance over joints present in both frames."""
    truth_by_joint = {k.joint: k for k in truth}
    dists: list[float] = []
    for p in pred:
        t = truth_by_joint.get(p.joint)
        if t is not None:
            dists.append(math.hypot(p.x - t.x, p.y - t.y))
    if not dists:
        return None
    return sum(dists) / len(dists)


def sample_error(
    pred_frames: tuple[tuple[Keypoint, ...], ...],
    truth_frames: tuple[tuple[Keypoint, ...], ...],
) -> float:
    """Mean per-keypoint error across all comparable frames of one sample."""
    errs = [
        e
        for pf, tf in zip(pred_frames, truth_frames, strict=False)
        if (e := _frame_error(pf, tf)) is not None
    ]
    # No comparable frames (e.g. the candidate rejected the clip) is a max-error
    # failure, not a free pass.
    return sum(errs) / len(errs) if errs else math.inf


def run_validation(
    model: PoseModel, golden: list[GoldenSample], *, tolerance: float = DEFAULT_TOLERANCE
) -> ValidationReport:
    """Evaluate ``model`` against the golden set; block if it regresses."""
    per_sample: dict[str, float] = {}
    for s in golden:
        result = compute_pose_run(model, frame_count=s.frame_count, width=s.width, height=s.height)
        per_sample[s.name] = sample_error(result.frames, s.truth_frames)
    mean_error = sum(per_sample.values()) / len(per_sample) if per_sample else math.inf
    return ValidationReport(
        mean_error=mean_error,
        per_sample=per_sample,
        passed=mean_error <= tolerance,
        tolerance=tolerance,
    )


def build_golden_from_reference(
    model: PoseModel, geometries: list[tuple[str, int, int, int]]
) -> list[GoldenSample]:
    """Freeze a reference model's output as the golden truth (fixture helper).

    ``geometries`` is a list of (name, frame_count, width, height). In
    production the truth comes from mocap, not a model — this is only for
    exercising the gate mechanism in tests/CI fixtures.
    """
    golden: list[GoldenSample] = []
    for name, fc, w, h in geometries:
        result = compute_pose_run(model, frame_count=fc, width=w, height=h)
        golden.append(
            GoldenSample(name=name, frame_count=fc, width=w, height=h, truth_frames=result.frames)
        )
    return golden
