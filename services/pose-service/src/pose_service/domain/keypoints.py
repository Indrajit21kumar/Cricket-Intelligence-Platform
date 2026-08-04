"""Canonical keypoint schema (M06 §5).

M06 emits a stable joint set so downstream modules (M09, M10) are
model-agnostic: whatever model runs behind the adapter, the schema out is
fixed. The canonical set is the 17 COCO body joints (min 17 per §5); a model
that produces more can extend, but downstream only relies on these.

Each keypoint carries (x, y, confidence); ``z`` + ``depth_estimated`` appear
only when a monocular 3D-lift is used (2D is always the reliable baseline,
Book 4 / feasibility "Amber"). x, y are in the CIP normalised frame after
Step 4 (0..1 of frame width/height); before normalisation they are raw pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: One decoded video frame (an OpenCV/numpy H x W x 3 BGR array). Kept as
#: ``Any`` so the adapter layer never forces numpy/OpenCV onto callers — the
#: fake path passes no frames at all.
FrameImage = Any

# The 17 canonical COCO joints, in a fixed order (index == downstream contract).
CANONICAL_JOINTS: tuple[str, ...] = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)

# subject_status values.
SUBJECT_TRACKED = "tracked"
SUBJECT_MULTI_AMBIGUOUS = "multi_subject_ambiguous"
SUBJECT_NONE = "no_subject"

# quality values.
QUALITY_OK = "ok"
QUALITY_PROVISIONAL = "provisional"
QUALITY_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class Keypoint:
    joint: str
    x: float
    y: float
    confidence: float
    z: float | None = None
    depth_estimated: bool = False


@dataclass(frozen=True, slots=True)
class PersonDetection:
    """One detected person in a frame (raw model output — pre-tracking)."""

    keypoints: tuple[Keypoint, ...]
    score: float  # overall detection score
    cx: float  # bbox centre x (pixels) — used by subject tracking
    cy: float
    area: float  # bbox area (pixels^2) — bigger = closer = more likely the batter


@dataclass(frozen=True, slots=True)
class FrameDetections:
    frame_index: int
    persons: tuple[PersonDetection, ...]
