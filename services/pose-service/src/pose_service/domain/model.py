"""Pose-model adapter + fake model + model registry version (M06 §11, FR-M06-07).

The pose model is a pluggable, GPU-served estimator (MediaPipe / MoveNet /
ViTPose) pinned to a registry version. The dev stack has no GPU or model, so —
exactly as M05 did for CV/storage — Step 1 ships a deterministic
:class:`FakePoseModel`; a real GPU model plugs into the same
:class:`PoseModel` protocol later, gated by the golden-dataset validation gate
(Step 7). ALL the real decision logic (subject tracking, confidence
aggregation, normalisation, artefact/event) is built for real on top.

``version`` is the pinned model id that lands in ``pose_runs.model_version`` —
the anchor for canary/rollback + the validation gate (ENG-007).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pose_service.domain.keypoints import (
    CANONICAL_JOINTS,
    FrameDetections,
    FrameImage,
    Keypoint,
    PersonDetection,
)

# Pinned model version (registry id). A real model change bumps this and must
# pass the golden-dataset gate before shipping.
MODEL_VERSION = "fake-pose-v1"


class PoseModel(Protocol):
    """Adapter every pose estimator (MediaPipe, MoveNet, ViTPose, fake) satisfies."""

    @property
    def version(self) -> str:
        """Registry version pinned to this model."""
        ...

    def infer(
        self,
        *,
        frame_count: int,
        width: int,
        height: int,
        frames: Sequence[FrameImage] | None = None,
    ) -> list[FrameDetections]:
        """Run the model over the clip's frames, returning raw per-frame detections.

        ``frames`` carries the decoded pixels when the clip loader actually
        read the video. It is optional because the fake model synthesises a
        skeleton from geometry alone; a real model requires it.
        """
        ...


class FakePoseModel:
    """Deterministic in-process pose model for dev + tests.

    Produces ``persons`` detections per frame with the 17 canonical joints,
    positioned smoothly across frames to simulate a batting motion. Observable
    + configurable via :meth:`patch` — the seam the multi-subject (Step 3) and
    low-confidence (Step 5) tests hang off.
    """

    def __init__(
        self, *, persons: int = 1, base_confidence: float = 0.9, comparable: bool = False
    ) -> None:
        self._version = MODEL_VERSION
        self.persons = persons
        self.base_confidence = base_confidence
        #: When True, extra people are the same size as person 0 — the
        #: "two batters in the net" case tracking must refuse to guess at.
        self.comparable = comparable

    @property
    def version(self) -> str:
        return self._version

    def patch(
        self,
        *,
        persons: int | None = None,
        base_confidence: float | None = None,
        comparable: bool | None = None,
    ) -> None:
        """One-shot test override for the next infer()."""
        if persons is not None:
            self.persons = persons
        if base_confidence is not None:
            self.base_confidence = base_confidence
        if comparable is not None:
            self.comparable = comparable

    def infer(
        self,
        *,
        frame_count: int,
        width: int,
        height: int,
        frames: Sequence[FrameImage] | None = None,
    ) -> list[FrameDetections]:
        _ = frames  # the fake synthesises from geometry; it reads no pixels
        detections: list[FrameDetections] = []
        for f in range(frame_count):
            phase = (f / max(frame_count - 1, 1)) * math.pi  # 0..pi across the clip
            persons: list[PersonDetection] = []
            for p in range(self.persons):
                # Person 0 is the batter: centred, large. Extra people are off to
                # the side and smaller, so tracking prefers the central/largest.
                # Under ``comparable`` they stand alongside the batter at the
                # same size — two players sharing a net, which no heuristic can
                # honestly separate.
                if self.comparable:
                    cx = width * (0.5 + 0.12 * p)
                    scale = 0.42 * height
                else:
                    cx = width * (0.5 if p == 0 else (0.15 + 0.7 * p))
                    scale = (0.42 if p == 0 else 0.28) * height
                cy = height * 0.55
                persons.append(
                    self._person(
                        cx=cx,
                        cy=cy,
                        scale=scale,
                        phase=phase,
                        primary=(p == 0 or self.comparable),
                    )
                )
            detections.append(FrameDetections(frame_index=f, persons=tuple(persons)))
        return detections

    def _person(
        self, *, cx: float, cy: float, scale: float, phase: float, primary: bool
    ) -> PersonDetection:
        # A simple, deterministic skeleton around (cx, cy). The wrists swing with
        # ``phase`` to imitate a stroke; other joints are roughly static.
        swing = math.sin(phase) * 0.18 * scale
        # Fractions of ``scale`` from the body centre for each joint (x, y).
        layout: dict[str, tuple[float, float]] = {
            "nose": (0.0, -0.50),
            "left_eye": (-0.04, -0.53),
            "right_eye": (0.04, -0.53),
            "left_ear": (-0.08, -0.52),
            "right_ear": (0.08, -0.52),
            "left_shoulder": (-0.16, -0.36),
            "right_shoulder": (0.16, -0.36),
            "left_elbow": (-0.22, -0.16),
            "right_elbow": (0.22, -0.16),
            "left_wrist": (-0.20 + swing / scale, 0.02),
            "right_wrist": (0.20 + swing / scale, 0.02),
            "left_hip": (-0.12, 0.0),
            "right_hip": (0.12, 0.0),
            "left_knee": (-0.13, 0.26),
            "right_knee": (0.13, 0.26),
            "left_ankle": (-0.13, 0.50),
            "right_ankle": (0.13, 0.50),
        }
        kps: list[Keypoint] = []
        for i, joint in enumerate(CANONICAL_JOINTS):
            fx, fy = layout[joint]
            # Small deterministic per-joint confidence jitter around the base.
            conf = max(0.0, min(1.0, self.base_confidence - 0.02 * (i % 3)))
            kps.append(Keypoint(joint=joint, x=cx + fx * scale, y=cy + fy * scale, confidence=conf))
        area = scale * scale
        return PersonDetection(
            keypoints=tuple(kps),
            score=self.base_confidence if primary else self.base_confidence * 0.9,
            cx=cx,
            cy=cy,
            area=area,
        )


class RealPoseModel:
    """YOLOv8-pose (ultralytics) over the clip's real decoded frames.

    YOLOv8-pose is COCO-trained and emits its 17 keypoints in exactly the
    order of :data:`CANONICAL_JOINTS`, so the mapping is positional — no
    remapping table, no silent joint-order bug.

    Everything downstream of this class (subject tracking, CIP-frame
    normalisation, confidence aggregation, quality policy) is unchanged: this
    only replaces where the detections come from.
    """

    def __init__(self, *, weights: str = "yolov8n-pose.pt") -> None:
        from ultralytics import YOLO  # lazy: only the real path needs ultralytics

        self._model = YOLO(weights)
        self._version = f"real-pose-yolov8-{Path(weights).stem}"

    @property
    def version(self) -> str:
        return self._version

    def infer(
        self,
        *,
        frame_count: int,
        width: int,
        height: int,
        frames: Sequence[FrameImage] | None = None,
    ) -> list[FrameDetections]:
        _ = (frame_count, width, height)  # geometry comes from the frames themselves
        if frames is None:
            raise ValueError("RealPoseModel needs decoded frames — pair it with RealClipLoader.")
        return [
            FrameDetections(frame_index=i, persons=self._detect(frame))
            for i, frame in enumerate(frames)
        ]

    def _detect(self, frame: FrameImage) -> tuple[PersonDetection, ...]:
        result = self._model(frame, verbose=False)[0]
        if result.keypoints is None or result.boxes is None:
            return ()
        xy, conf, boxes = result.keypoints.xy, result.keypoints.conf, result.boxes
        persons: list[PersonDetection] = []
        for p in range(len(boxes)):
            keypoints = tuple(
                Keypoint(
                    joint=joint,
                    x=float(xy[p, j, 0]),
                    y=float(xy[p, j, 1]),
                    confidence=float(conf[p, j]) if conf is not None else 0.0,
                )
                for j, joint in enumerate(CANONICAL_JOINTS)
            )
            x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[p])
            persons.append(
                PersonDetection(
                    keypoints=keypoints,
                    score=float(boxes.conf[p]),
                    cx=(x1 + x2) / 2.0,
                    cy=(y1 + y2) / 2.0,
                    area=(x2 - x1) * (y2 - y1),
                )
            )
        return tuple(persons)
