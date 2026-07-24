"""M06 pose reader — wrists + the CIP frame they live in (M07 Step 4, FR-M07-04).

M07 needs two things from M06: where the batter's hands are (to tell which bat
is theirs) and which coordinate frame those hands are expressed in (to put the
bat in that same frame). ``pose.keypoints`` carries both — the keypoint
artefact plus the ``frame`` block giving the pixel origin and divisor.

The reader is an adapter with a fake, like every other external dependency in
the vision stack. The real one fetches the artefact from object storage; the
fake serves an in-memory payload so association can be tested without S3.

Missing pose is an expected state, not an error: M06 rejects clips it cannot
track (multi-subject, no subject), and M07 must still run — it just loses the
hand-bat association and says so, rather than failing the clip outright.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

LEFT_WRIST = "left_wrist"
RIGHT_WRIST = "right_wrist"


@dataclass(frozen=True, slots=True)
class CipFrame:
    """The transform M06 applied: pixel origin, divisor, Y-up."""

    origin_x: float
    origin_y: float
    scale: float

    def to_cip(self, x: float, y: float) -> tuple[float, float]:
        """Map a pixel point into the CIP frame (Y flipped, origin at stance)."""
        s = self.scale if self.scale else 1.0
        return ((x - self.origin_x) / s, (self.origin_y - y) / s)


@dataclass(frozen=True, slots=True)
class WristPair:
    """Both wrists in one frame, in CIP coordinates. Either may be absent."""

    frame_index: int
    left: tuple[float, float] | None = None
    right: tuple[float, float] | None = None
    confidence: float = 0.0

    @property
    def midpoint(self) -> tuple[float, float] | None:
        """Where the hands are — the anchor a held bat's handle sits near."""
        if self.left is not None and self.right is not None:
            return ((self.left[0] + self.right[0]) / 2, (self.left[1] + self.right[1]) / 2)
        return self.left or self.right


@dataclass(frozen=True, slots=True)
class PoseTrack:
    """What M07 uses from an M06 run."""

    frame: CipFrame
    wrists: tuple[WristPair, ...]

    def at(self, frame_index: int) -> WristPair | None:
        for w in self.wrists:
            if w.frame_index == frame_index:
                return w
        return None


def parse_pose_artefact(payload: str) -> PoseTrack:
    """Read wrists + the CIP frame out of an M06 keypoint artefact."""
    data = json.loads(payload)
    block = data.get("frame") or {}
    frame = CipFrame(
        origin_x=float(block.get("origin_x", 0.0)),
        origin_y=float(block.get("origin_y", 0.0)),
        scale=float(block.get("scale", 1.0)),
    )
    wrists: list[WristPair] = []
    for index, keypoints in enumerate(data.get("frames", [])):
        left: tuple[float, float] | None = None
        right: tuple[float, float] | None = None
        confidences: list[float] = []
        for kp in keypoints:
            if kp.get("joint") == LEFT_WRIST:
                left = (float(kp["x"]), float(kp["y"]))
                confidences.append(float(kp.get("confidence", 0.0)))
            elif kp.get("joint") == RIGHT_WRIST:
                right = (float(kp["x"]), float(kp["y"]))
                confidences.append(float(kp.get("confidence", 0.0)))
        wrists.append(
            WristPair(
                frame_index=index,
                left=left,
                right=right,
                confidence=min(confidences) if confidences else 0.0,
            )
        )
    return PoseTrack(frame=frame, wrists=tuple(wrists))


class PoseClient(Protocol):
    """Fetches the M06 pose track for a clip."""

    async def load(self, artefact_ref: str) -> PoseTrack | None:
        """Return the pose track, or None when M06 produced no usable run."""
        ...


class FakePoseClient:
    """In-process pose client for dev + tests.

    ``set_payload`` accepts a real M06 artefact string, so the association
    tests exercise the actual published format rather than a convenient
    parallel structure that could drift from it.
    """

    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}
        #: When True, behaves as if M06 produced nothing for the clip.
        self.missing = False

    def set_payload(self, artefact_ref: str, payload: str) -> None:
        self.payloads[artefact_ref] = payload

    async def load(self, artefact_ref: str) -> PoseTrack | None:
        if self.missing:
            return None
        payload = self.payloads.get(artefact_ref)
        return parse_pose_artefact(payload) if payload else None
