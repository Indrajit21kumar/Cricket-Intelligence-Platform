"""The normalised stroke - M10's single working representation (M10 §4-5).

Everything the fan-in delivers, mapped once into the CIP frame and metric units,
so every BM formula reads from one consistent structure rather than re-deriving
coordinates. Building it is Step 2; the formulas (Step 4) are pure functions of
it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from biomechanics_service.domain.geometry import Point3D

# Handedness.
RHB = "RHB"
LHB = "LHB"

# Camera angles (from M05), which fix the depth axis.
ANGLE_SIDE_ON = "side_on"
ANGLE_FRONT_ON = "front_on"

# Spatial confidence (from M05 calibration).
SPATIAL_HIGH = "high"
SPATIAL_MEDIUM = "medium"
SPATIAL_LOW = "low"

# COCO joints M10 uses.
NOSE = "nose"
LEFT_SHOULDER = "left_shoulder"
RIGHT_SHOULDER = "right_shoulder"
LEFT_HIP = "left_hip"
RIGHT_HIP = "right_hip"
LEFT_KNEE = "left_knee"
RIGHT_KNEE = "right_knee"
LEFT_ANKLE = "left_ankle"
RIGHT_ANKLE = "right_ankle"
LEFT_WRIST = "left_wrist"
RIGHT_WRIST = "right_wrist"

# Bat parts (from M07).
HANDLE_TOP = "handle_top"
HANDLE_BOTTOM = "handle_bottom"
BLADE_TIP = "blade_tip"
SWEET_SPOT = "sweet_spot"


@dataclass(frozen=True, slots=True)
class PoseFrame:
    frame_index: int
    joints: dict[str, Point3D]
    mean_confidence: float

    def get(self, joint: str) -> Point3D | None:
        return self.joints.get(joint)


@dataclass(frozen=True, slots=True)
class BatFrame:
    frame_index: int
    parts: dict[str, Point3D]
    detected: bool

    def get(self, part: str) -> Point3D | None:
        return self.parts.get(part)


@dataclass(frozen=True, slots=True)
class Phases:
    stance: int
    backlift: int
    downswing: int
    impact: int
    follow_through: int
    method: str


@dataclass(frozen=True, slots=True)
class BallContext:
    """Timing anchors from M08."""

    release_frame: int | None
    contact_frame: int | None
    timing_reference: str  # release_relative | absolute


@dataclass(frozen=True, slots=True)
class Anthropometrics:
    """From M04. Height drives stride-as-%-height; stance drives handedness."""

    height_cm: float | None
    handedness: str  # RHB | LHB
    age_band: str | None = None


@dataclass(frozen=True, slots=True)
class Calibration:
    """From M05, plus the M06 frame scale needed to reach metres."""

    #: Metres per normalised CIP-frame unit - the single multiplier from the
    #: normalised (frame-height) coordinates to metres. = frame_scale_px x
    #: pixel_to_meter.
    metres_per_unit: float | None
    fps: float
    camera_angle: str
    spatial_confidence: str
    depth_estimated: bool


@dataclass(frozen=True, slots=True)
class NormalisedStroke:
    """The whole stroke in the CIP frame, handedness-mirrored, in metres."""

    correlation_id: str
    pose_frames: tuple[PoseFrame, ...]
    bat_frames: tuple[BatFrame, ...]
    phases: Phases
    ball: BallContext
    anthropometrics: Anthropometrics
    calibration: Calibration
    shot_type: str | None = None
    shot_confidence: float | None = None
    #: Fraction of downswing frames M07 failed to detect the bat (drives the
    #: bat-dependent provisional rule); None when no bat data.
    bat_downswing_failure_ratio: float | None = None
    #: Which frames actually detected the bat, for the >30% rule.
    bat_detected_frames: frozenset[int] = field(default_factory=frozenset)

    @property
    def frame_count(self) -> int:
        return len(self.pose_frames)

    def pose_at(self, frame_index: int) -> PoseFrame | None:
        for f in self.pose_frames:
            if f.frame_index == frame_index:
                return f
        return None

    def bat_at(self, frame_index: int) -> BatFrame | None:
        for f in self.bat_frames:
            if f.frame_index == frame_index:
                return f
        return None
