"""3D geometry primitives in the CIP frame (M10 §5, Book 4 Ch. 2).

The CIP batting frame: origin at the ground beneath mid-stance, X along the
crease (positive off-side for the normalised right-hand frame), Y vertical, Z
down the pitch toward the bowler. All BM formulas operate here.

A single monocular camera cannot resolve one horizontal axis - it becomes
depth. Which axis depends on the camera angle (side-on sees down-pitch, so X is
depth; front-on sees the crease, so Z is depth). Every :class:`Point3D`
therefore carries ``depth_estimated`` for the axis that was inferred rather than
seen, and formulas that lean on an estimated axis inherit reduced confidence.
Keeping that flag ON THE POINT rather than on the metric is deliberate: it
cannot be lost between the coordinate transform and the formula that uses it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point3D:
    """A point in the CIP frame. Units are metres once calibration is applied."""

    x: float
    y: float
    z: float = 0.0
    #: True when a horizontal axis (X or Z) was inferred, not measured.
    depth_estimated: bool = False

    def __sub__(self, other: Point3D) -> Vector3D:
        return Vector3D(self.x - other.x, self.y - other.y, self.z - other.z)

    def mirrored_x(self) -> Point3D:
        """Reflect across the vertical plane - the handedness mirror (X -> -X)."""
        return Point3D(-self.x, self.y, self.z, self.depth_estimated)


@dataclass(frozen=True, slots=True)
class Vector3D:
    x: float
    y: float
    z: float = 0.0

    @property
    def magnitude(self) -> float:
        return math.sqrt(self.x * self.x + self.y * self.y + self.z * self.z)

    def dot(self, other: Vector3D) -> float:
        return self.x * other.x + self.y * other.y + self.z * other.z


def midpoint(a: Point3D, b: Point3D) -> Point3D:
    """Midpoint, depth-estimated if either endpoint was."""
    return Point3D(
        (a.x + b.x) / 2,
        (a.y + b.y) / 2,
        (a.z + b.z) / 2,
        a.depth_estimated or b.depth_estimated,
    )


def angle_between(v1: Vector3D, v2: Vector3D) -> float:
    """Interior angle between two vectors, in degrees (0..180).

    Returns 0.0 for a zero-length vector rather than raising - a degenerate
    input yields a degenerate-but-finite metric the caller can flag, never a
    crash mid-stroke.
    """
    denom = v1.magnitude * v2.magnitude
    if denom == 0.0:
        return 0.0
    cos_theta = max(-1.0, min(1.0, v1.dot(v2) / denom))
    return math.degrees(math.acos(cos_theta))


def planar_angle(dz: float, dx: float) -> float:
    """Angle in the X-Z (top-down) plane, degrees. Used for shoulder/hip lines.

    ``atan2(Z, X)`` per the BM-02/03 definition: the rotation of a body line
    viewed from above, where the line runs between left/right keypoints.
    """
    return math.degrees(math.atan2(dz, dx))


def signed_angle_from_vertical(dx: float, dy: float) -> float:
    """Angle of a 2D segment from the vertical Y axis, degrees (-180..180).

    Positive toward +X. Used for bat angle and pelvic/foot lines in the
    vertical plane. Matches M07's bat-angle convention so a bat angle measured
    here agrees with the one M07 published.
    """
    return math.degrees(math.atan2(dx, dy))
