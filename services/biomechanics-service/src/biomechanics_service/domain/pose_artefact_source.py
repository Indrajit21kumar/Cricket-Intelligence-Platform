"""Read M06's keypoint artefact and assemble a pose-only stroke (Pose-First MVP).

The normal :class:`~biomechanics_service.domain.sources.StrokeSource` wants six
upstream inputs, three of which are stubs. This source uses the one input that
is genuinely measured — the keypoint artefact M06 writes — and builds the
stroke from that alone.

It reads the artefact off the shared local storage root rather than calling
pose-service over HTTP. The keypoint payload is large and already written to
storage by design (M06 §Step 6 splits the artefact from the DB summary
precisely so it is not passed around in messages), so reading the object is
the intended access path, not a shortcut. A real deployment swaps the local
root for the same object store both services point at.

Returning None when the artefact is missing is correct, not a failure: M06
writes no artefact when it rejected the clip (multi-subject, no subject), and
there is nothing to measure without a body.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from biomechanics_service.domain.builder import RawPoseFrame, RawStroke
from biomechanics_service.domain.pose_only import build_pose_only_stroke
from biomechanics_service.domain.stroke import RHB, Anthropometrics, Calibration


#: Mirrors pose_service.domain.artefact.artefact_key. Duplicated deliberately:
#: a cross-service import would couple the two deployables, and the key format
#: is part of the storage contract between them, not private to either.
def artefact_key(*, tenant_id: str, correlation_id: str) -> str:
    return f"tenant/{tenant_id}/pose/{correlation_id}/keypoints.json"


def parse_pose_artefact(payload: str) -> list[RawPoseFrame]:
    """Turn M06's serialised keypoint payload into raw pose frames.

    Frames M06 emitted as empty (no tracked subject in that frame) are skipped
    rather than represented as a frame with no joints, so the metric formulas
    see only frames that actually observed a body.
    """
    document: Any = json.loads(payload)
    frames = document.get("frames") if isinstance(document, dict) else None
    if not isinstance(frames, list):
        return []

    out: list[RawPoseFrame] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, list) or not frame:
            continue
        joints: dict[str, tuple[float, float, float]] = {}
        for keypoint in frame:
            if not isinstance(keypoint, dict):
                continue
            joint = keypoint.get("joint")
            x, y = keypoint.get("x"), keypoint.get("y")
            if not isinstance(joint, str):
                continue
            if not isinstance(x, int | float) or not isinstance(y, int | float):
                continue
            confidence = keypoint.get("confidence")
            joints[joint] = (
                float(x),
                float(y),
                float(confidence) if isinstance(confidence, int | float) else 0.0,
            )
        if joints:
            out.append(RawPoseFrame(frame_index=index, joints=joints))
    return out


class PoseOnlyStrokeSource:
    """Assembles a stroke from M06's artefact — no bat, ball or shot input.

    ``fps`` and the capture context come from the caller because M06's
    artefact carries keypoints, not capture metadata. Both default to the
    honest unknown: no metric scale, no resolved camera angle.
    """

    def __init__(self, *, root: Path, fps: float = 30.0) -> None:
        self._root = root
        self._fps = fps

    async def load(self, correlation_id: str) -> RawStroke | None:
        matches = sorted(self._root.glob(f"tenant/*/pose/{correlation_id}/keypoints.json"))
        if not matches:
            return None
        pose = parse_pose_artefact(matches[0].read_text(encoding="utf-8"))
        if not pose:
            return None
        return build_pose_only_stroke(
            correlation_id=correlation_id,
            pose=pose,
            calibration=Calibration(
                # No stump detector and no angle classifier exist, so both are
                # reported unknown. The quality gates then disable the metrics
                # that would need them, rather than publishing wrong units.
                metres_per_unit=None,
                fps=self._fps,
                camera_angle="other",
                spatial_confidence="low",
                depth_estimated=True,
            ),
            anthropometrics=Anthropometrics(height_cm=None, handedness=RHB),
        )
