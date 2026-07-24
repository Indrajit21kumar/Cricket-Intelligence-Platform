"""Bat compute pipeline (M07 Steps 3-6 orchestration).

One pure function ties the stages together, so the whole run is testable with
no DB, GPU or broker:

    detect -> track + associate to the hands -> derive angles + swing plane
    -> aggregate confidence -> apply the degradation policy

Step 7 wraps this with I/O (artefact, bat_runs, event, annotation queue); it
adds no decisions of its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from bat_service.domain.bat import BatFrame
from bat_service.domain.degradation import DegradationResult, assess
from bat_service.domain.detector import BatDetector
from bat_service.domain.geometry import BatAngle, SwingPlane, bat_angles, swing_plane
from bat_service.domain.pose_client import CipFrame, PoseTrack
from bat_service.domain.tracking import track_bat

#: Coordinates are in the true CIP frame — origin at the stance point, from M06.
FRAME_BASIS_CIP = "cip"
#: No pose was available, so coordinates are only clip-relative: scaled by frame
#: height (which keeps distances resolution-independent) but with no stance
#: origin. Distances and angles hold; absolute positions do NOT line up with
#: body geometry, and M10 must not mix the two.
FRAME_BASIS_CLIP_RELATIVE = "clip_relative"


@dataclass(frozen=True, slots=True)
class BatRunResult:
    model_version: str
    dataset_version: str | None
    frame_count: int
    frames: tuple[BatFrame, ...]
    angles: tuple[BatAngle, ...]
    plane: SwingPlane | None
    degradation: DegradationResult
    #: Per-frame association method — hands | continuity | sole_candidate | none.
    associations: tuple[str, ...]
    #: cip | clip_relative — which frame these coordinates are actually in.
    frame_basis: str

    @property
    def hand_associated_frames(self) -> int:
        """Frames attributed via the batter's hands, the strongest evidence."""
        return sum(1 for a in self.associations if a == "hands")


def compute_bat_run(
    detector: BatDetector,
    *,
    frame_count: int,
    width: int,
    height: int,
    pose: PoseTrack | None,
) -> BatRunResult:
    """Run the full bat pipeline over a clip's frame geometry."""
    detections = detector.detect(frame_count=frame_count, width=width, height=height)

    # Without M06 there is no stance origin, but there is still a scale: the
    # clip's own height. Using it keeps every threshold in this module
    # resolution-independent instead of silently comparing CIP-unit limits
    # against raw pixels. The result is honestly labelled clip_relative.
    fallback = CipFrame(origin_x=0.0, origin_y=0.0, scale=float(height or 1))
    tracked = track_bat(detections, pose=pose, cip_frame=None if pose else fallback)
    angles = bat_angles(tracked.frames)
    plane = swing_plane(tracked.frames)
    degradation = assess(tracked.frames)
    return BatRunResult(
        model_version=detector.version,
        dataset_version=detector.dataset_version,
        frame_count=frame_count,
        frames=tracked.frames,
        angles=angles,
        plane=plane,
        degradation=degradation,
        associations=tracked.associations,
        frame_basis=FRAME_BASIS_CIP if pose is not None else FRAME_BASIS_CLIP_RELATIVE,
    )
