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
from typing import Protocol

from pose_service.domain.keypoints import (
    CANONICAL_JOINTS,
    FrameDetections,
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

    def infer(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        """Run the model over the clip's frames, returning raw per-frame detections."""
        ...


class FakePoseModel:
    """Deterministic in-process pose model for dev + tests.

    Produces ``persons`` detections per frame with the 17 canonical joints,
    positioned smoothly across frames to simulate a batting motion. Observable
    + configurable via :meth:`patch` — the seam the multi-subject (Step 3) and
    low-confidence (Step 5) tests hang off.
    """

    def __init__(self, *, persons: int = 1, base_confidence: float = 0.9) -> None:
        self._version = MODEL_VERSION
        self.persons = persons
        self.base_confidence = base_confidence

    @property
    def version(self) -> str:
        return self._version

    def patch(self, *, persons: int | None = None, base_confidence: float | None = None) -> None:
        """One-shot test override for the next infer()."""
        if persons is not None:
            self.persons = persons
        if base_confidence is not None:
            self.base_confidence = base_confidence

    def infer(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        frames: list[FrameDetections] = []
        for f in range(frame_count):
            phase = (f / max(frame_count - 1, 1)) * math.pi  # 0..pi across the clip
            persons: list[PersonDetection] = []
            for p in range(self.persons):
                # Person 0 is the batter: centred, large. Extra people are off to
                # the side and smaller (so tracking prefers the central/largest).
                cx = width * (0.5 if p == 0 else (0.15 + 0.7 * p))
                cy = height * 0.55
                scale = (0.42 if p == 0 else 0.28) * height
                persons.append(
                    self._person(cx=cx, cy=cy, scale=scale, phase=phase, primary=(p == 0))
                )
            frames.append(FrameDetections(frame_index=f, persons=tuple(persons)))
        return frames

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
