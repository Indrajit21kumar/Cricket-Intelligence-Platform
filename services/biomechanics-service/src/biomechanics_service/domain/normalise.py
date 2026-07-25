"""Map raw perception coordinates into the CIP frame (M10 Step 2, FR-M10-02).

Two transforms, applied once when the stroke is assembled:

**Image axes -> CIP axes, by camera angle.** M06 delivers keypoints in a
normalised 2D image frame (image-x horizontal, y up, origin at stance). The CIP
frame is 3D (X crease, Y vertical, Z down pitch). A single camera resolves the
vertical and ONE horizontal axis; the other is depth:

- side-on: the camera looks across the pitch, so image-x runs DOWN the pitch ->
  Z. The crease axis X points at/away from the camera -> depth-estimated.
- front-on: the camera looks down the pitch, so image-x runs along the crease ->
  X. The down-pitch axis Z -> depth-estimated.

The unresolved axis is set to 0 and flagged ``depth_estimated`` so every metric
that touches it inherits the reduced confidence. This is honest about what a
phone can and cannot see, which is the whole point of the CIP-STD trust doctrine.

**Handedness mirror (AC-M10-05).** "Off side" is opposite for a left-hander, so
the same shot has mirror-image coordinates. To make every downstream metric
handedness-agnostic, a left-hander's stroke is reflected across the vertical
plane (X -> -X) at ingestion. After this, an LHB cover drive and an RHB cover
drive have the same normalised signature, so one set of formulas and one set of
benchmark ranges serve both - no handedness branches anywhere downstream.

**Scale.** Normalised coordinates are in frame-height units; multiplying by
``metres_per_unit`` (M06 frame scale x M05 pixel_to_meter) puts them in metres,
which is what the linear/velocity formulas need.
"""

from __future__ import annotations

from biomechanics_service.domain.geometry import Point3D
from biomechanics_service.domain.stroke import (
    ANGLE_FRONT_ON,
    ANGLE_SIDE_ON,
    LHB,
)


def to_cip(
    image_x: float,
    image_y: float,
    *,
    camera_angle: str,
    metres_per_unit: float,
    handedness: str,
) -> Point3D:
    """Map one normalised 2D image point into the CIP frame, in metres.

    Applies the camera-angle axis assignment, the depth flag, the metric scale,
    and the handedness mirror - the full Step 2 transform for a single point.
    """
    x_m = image_x * metres_per_unit
    y_m = image_y * metres_per_unit

    if camera_angle == ANGLE_SIDE_ON:
        # Image-x is down the pitch (Z); the crease axis X is depth.
        point = Point3D(x=0.0, y=y_m, z=x_m, depth_estimated=True)
    elif camera_angle == ANGLE_FRONT_ON:
        # Image-x is along the crease (X); the down-pitch axis Z is depth.
        point = Point3D(x=x_m, y=y_m, z=0.0, depth_estimated=True)
    else:
        # An unsupported angle resolves neither horizontal axis cleanly; keep
        # image-x as X best-effort and mark it estimated. Step 5 lowers spatial
        # confidence and disables the X-dependent metrics for this case.
        point = Point3D(x=x_m, y=y_m, z=0.0, depth_estimated=True)

    if handedness == LHB:
        point = point.mirrored_x()
    return point


def is_supported_angle(camera_angle: str) -> bool:
    """True for the two angles that resolve a horizontal axis to a real one."""
    return camera_angle in (ANGLE_SIDE_ON, ANGLE_FRONT_ON)
