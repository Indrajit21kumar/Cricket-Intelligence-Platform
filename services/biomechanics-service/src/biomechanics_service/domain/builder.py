"""Assemble a NormalisedStroke from raw image-space inputs (M10 Step 2).

The fan-in arrives in image space (M06/M07 normalised 2D coordinates). This
applies the Step 2 transforms — camera-angle axis mapping, depth flag,
handedness mirror, metric scale — to every keypoint once, producing the single
NormalisedStroke the formulas read. The source adapters (Step 7) fetch the raw
inputs; this turns them into the working representation.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from biomechanics_service.domain.normalise import to_cip
from biomechanics_service.domain.stroke import (
    Anthropometrics,
    BallContext,
    BatFrame,
    Calibration,
    NormalisedStroke,
    Phases,
    PoseFrame,
)

#: A raw keypoint: (image_x, image_y, confidence) in M06's normalised 2D frame.
RawPoint = tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class RawPoseFrame:
    frame_index: int
    joints: dict[str, RawPoint]


@dataclass(frozen=True, slots=True)
class RawBatFrame:
    frame_index: int
    detected: bool
    #: (image_x, image_y) per part; no per-part confidence needed here.
    parts: dict[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawStroke:
    """Everything the fan-in provides, in image space, before normalisation."""

    correlation_id: str
    pose: tuple[RawPoseFrame, ...]
    bat: tuple[RawBatFrame, ...]
    phases: Phases
    ball: BallContext
    anthropometrics: Anthropometrics
    calibration: Calibration
    shot_type: str | None = None
    shot_confidence: float | None = None
    bat_downswing_failure_ratio: float | None = None


def build_normalised_stroke(raw: RawStroke) -> NormalisedStroke:
    """Apply the Step 2 transforms to every keypoint and bundle the stroke."""
    cal = raw.calibration
    # A missing scale means no metric-unit conversion is possible; carry 1.0 so
    # coordinates stay in frame-height units and Step 5 marks the run degraded.
    scale = cal.metres_per_unit if cal.metres_per_unit else 1.0
    handedness = raw.anthropometrics.handedness

    pose_frames: list[PoseFrame] = []
    for rf in raw.pose:
        joints = {}
        confidences: list[float] = []
        for joint, (ix, iy, conf) in rf.joints.items():
            joints[joint] = to_cip(
                ix,
                iy,
                camera_angle=cal.camera_angle,
                metres_per_unit=scale,
                handedness=handedness,
            )
            confidences.append(conf)
        mean_conf = sum(confidences) / len(confidences) if confidences else 0.0
        pose_frames.append(
            PoseFrame(frame_index=rf.frame_index, joints=joints, mean_confidence=mean_conf)
        )

    bat_frames: list[BatFrame] = []
    detected_frames: set[int] = set()
    for bf in raw.bat:
        parts = {
            part: to_cip(
                ix,
                iy,
                camera_angle=cal.camera_angle,
                metres_per_unit=scale,
                handedness=handedness,
            )
            for part, (ix, iy) in bf.parts.items()
        }
        bat_frames.append(BatFrame(frame_index=bf.frame_index, parts=parts, detected=bf.detected))
        if bf.detected:
            detected_frames.add(bf.frame_index)

    return NormalisedStroke(
        correlation_id=raw.correlation_id,
        pose_frames=tuple(pose_frames),
        bat_frames=tuple(bat_frames),
        phases=raw.phases,
        ball=raw.ball,
        anthropometrics=raw.anthropometrics,
        calibration=raw.calibration,
        shot_type=raw.shot_type,
        shot_confidence=raw.shot_confidence,
        bat_downswing_failure_ratio=raw.bat_downswing_failure_ratio,
        bat_detected_frames=frozenset(detected_frames),
    )
