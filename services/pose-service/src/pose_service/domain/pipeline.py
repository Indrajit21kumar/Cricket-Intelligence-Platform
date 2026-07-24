"""Pose compute pipeline (M06 Steps 2-5 orchestration).

One pure function ties the stages together so the whole pose run is testable
without any DB / GPU / Kafka:

    model.infer  →  primary-subject track  →  normalise to CIP frame  →
    aggregate confidence  →  resolve quality

Step 2 (endpoint + video.normalized consumer) and Step 6 (persist artefact +
publish pose.keypoints) are thin wrappers around this — they add I/O, not
logic. A real GPU model swaps in behind the same ``PoseModel`` protocol; this
orchestration is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass

from pose_service.domain.confidence import aggregate_confidence, resolve_quality
from pose_service.domain.keypoints import Keypoint
from pose_service.domain.model import PoseModel
from pose_service.domain.normalise import normalise
from pose_service.domain.tracking import select_primary_subject


@dataclass(frozen=True, slots=True)
class PoseRunResult:
    model_version: str
    frame_count: int
    subject_status: str
    #: Per-frame normalised keypoints of the tracked batter (empty if rejected).
    frames: tuple[tuple[Keypoint, ...], ...]
    mean_confidence: float
    quality: str  # ok | provisional | rejected
    depth_estimated: bool


def compute_pose_run(
    model: PoseModel,
    *,
    frame_count: int,
    width: int,
    height: int,
    depth_estimated: bool = True,
) -> PoseRunResult:
    """Run the full pose pipeline over a clip's frame geometry.

    ``depth_estimated`` is a property of the *capture*, not of this stage —
    M05 knows whether the clip was monocular and says so on
    ``video.normalized``; M06 carries that truth through rather than
    re-deciding it (Book 4 Ch. 2).
    """
    detections = model.infer(frame_count=frame_count, width=width, height=height)
    tracking = select_primary_subject(detections, width=float(width))

    # Rejected (multi/no subject): emit nothing usable but report why.
    if not tracking.frames:
        return PoseRunResult(
            model_version=model.version,
            frame_count=frame_count,
            subject_status=tracking.subject_status,
            frames=(),
            mean_confidence=0.0,
            quality=resolve_quality(subject_status=tracking.subject_status, provisional=True),
            depth_estimated=depth_estimated,
        )

    normalised = normalise(tracking.frames, frame_height=height, depth_estimated=depth_estimated)
    conf = aggregate_confidence(normalised.frames)
    quality = resolve_quality(subject_status=tracking.subject_status, provisional=conf.provisional)
    return PoseRunResult(
        model_version=model.version,
        frame_count=frame_count,
        subject_status=tracking.subject_status,
        frames=normalised.frames,
        mean_confidence=conf.mean_confidence,
        quality=quality,
        depth_estimated=normalised.depth_estimated,
    )
