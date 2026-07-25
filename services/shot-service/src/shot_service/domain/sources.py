"""Upstream signal readers: pose, bat, ball (M09 §8, FR-M09-04).

M09 is the first module that consumes DERIVED artefacts rather than raw video.
Pose (M06) is the required input — M06 is a hard dependency; bat (M07) and ball
(M08) are optional and improve accuracy. So each source is an adapter with a
fake, and the feature builder degrades gracefully to whatever is present.

Each parser reads the ACTUAL published shape, so a change to what M06/M07/M08
emit breaks a test here rather than silently producing wrong features:

- pose: the ``pose.keypoints/1.1`` artefact (per-frame COCO joints, already in
  the CIP frame).
- bat: the ``bat.tracked`` event payload (swing_plane inclination directly).
- ball: the ``ball.events`` payload (contact frame + timing_reference + line).

The sources are keyed on correlation_id, since that is what threads a stroke
through the whole pipeline. The real implementations fetch from the upstream
services (their GET endpoints / stores); the fakes hold what a test provides.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

# COCO joints M09 reads. Both wrists because a batter has two hands on the bat.
LEFT_WRIST = "left_wrist"
RIGHT_WRIST = "right_wrist"
LEFT_SHOULDER = "left_shoulder"
RIGHT_SHOULDER = "right_shoulder"
LEFT_HIP = "left_hip"
RIGHT_HIP = "right_hip"
LEFT_ANKLE = "left_ankle"
RIGHT_ANKLE = "right_ankle"


@dataclass(frozen=True, slots=True)
class PoseFrame:
    frame_index: int
    #: joint name -> (x, y, confidence), in the CIP frame (Y-up).
    joints: dict[str, tuple[float, float, float]]

    def point(self, joint: str) -> tuple[float, float] | None:
        j = self.joints.get(joint)
        return (j[0], j[1]) if j is not None else None

    def midpoint(self, a: str, b: str) -> tuple[float, float] | None:
        pa, pb = self.point(a), self.point(b)
        if pa is not None and pb is not None:
            return ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        return pa or pb


@dataclass(frozen=True, slots=True)
class PoseSequence:
    frames: tuple[PoseFrame, ...]

    @property
    def frame_count(self) -> int:
        return len(self.frames)


def parse_pose_artefact(payload: str) -> PoseSequence:
    """Parse an M06 keypoint artefact into a per-frame joint sequence."""
    data = json.loads(payload)
    frames: list[PoseFrame] = []
    for index, keypoints in enumerate(data.get("frames", [])):
        joints: dict[str, tuple[float, float, float]] = {}
        for kp in keypoints:
            joint = kp.get("joint")
            if joint is not None:
                joints[str(joint)] = (
                    float(kp["x"]),
                    float(kp["y"]),
                    float(kp.get("confidence", 0.0)),
                )
        frames.append(PoseFrame(frame_index=index, joints=joints))
    return PoseSequence(frames=tuple(frames))


@dataclass(frozen=True, slots=True)
class BatSummary:
    """What M09 uses from ``bat.tracked``."""

    swing_plane_inclination: float | None
    frames_detected: int
    provisional: bool

    @classmethod
    def from_event(cls, payload: dict[str, Any]) -> BatSummary:
        plane = payload.get("swing_plane") or {}
        inclination = plane.get("inclination_degrees")
        return cls(
            swing_plane_inclination=float(inclination) if inclination is not None else None,
            frames_detected=int(payload.get("frames_detected", 0)),
            provisional=bool(payload.get("provisional", False)),
        )


@dataclass(frozen=True, slots=True)
class BallSummary:
    """What M09 uses from ``ball.events``.

    ``usable_contact`` is the fusion of two upstream facts: a contact event was
    detected AND M08 anchored timing to release (not the absolute-timing
    fallback). Only then does M09 trust the contact frame enough to anchor
    standard phase segmentation on it (AC-M09-04).
    """

    contact_frame: int | None
    timing_reference: str
    line: str | None
    length: str | None
    conditions_met: bool

    @property
    def usable_contact(self) -> bool:
        return (
            self.contact_frame is not None
            and self.timing_reference == "release_relative"
            and self.conditions_met
        )

    @classmethod
    def from_event(cls, payload: dict[str, Any]) -> BallSummary:
        events = payload.get("events") or {}
        contact = events.get("contact") or {}
        line = events.get("line") or {}
        length = events.get("length") or {}
        contact_frame = contact.get("frame_index")
        return cls(
            contact_frame=int(contact_frame) if contact_frame is not None else None,
            timing_reference=str(events.get("timing_reference", "absolute")),
            line=line.get("value"),
            length=length.get("value"),
            conditions_met=bool(payload.get("conditions_met", False)),
        )


class PoseSource(Protocol):
    async def load(self, correlation_id: str) -> PoseSequence | None: ...


class BatSource(Protocol):
    async def load(self, correlation_id: str) -> BatSummary | None: ...


class BallSource(Protocol):
    async def load(self, correlation_id: str) -> BallSummary | None: ...


class FakePoseSource:
    """In-process pose source; ``set_payload`` takes a real M06 artefact."""

    def __init__(self) -> None:
        self.payloads: dict[str, str] = {}
        self.missing = False

    def set_payload(self, correlation_id: str, payload: str) -> None:
        self.payloads[correlation_id] = payload

    async def load(self, correlation_id: str) -> PoseSequence | None:
        if self.missing:
            return None
        payload = self.payloads.get(correlation_id)
        return parse_pose_artefact(payload) if payload else None


class FakeBatSource:
    """In-process bat source; ``set_event`` takes a real bat.tracked payload."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.missing = False

    def set_event(self, correlation_id: str, payload: dict[str, Any]) -> None:
        self.events[correlation_id] = payload

    async def load(self, correlation_id: str) -> BatSummary | None:
        if self.missing:
            return None
        payload = self.events.get(correlation_id)
        return BatSummary.from_event(payload) if payload is not None else None


class FakeBallSource:
    """In-process ball source; ``set_event`` takes a real ball.events payload."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.missing = False

    def set_event(self, correlation_id: str, payload: dict[str, Any]) -> None:
        self.events[correlation_id] = payload

    async def load(self, correlation_id: str) -> BallSummary | None:
        if self.missing:
            return None
        payload = self.events.get(correlation_id)
        return BallSummary.from_event(payload) if payload is not None else None
