"""Bat angle + swing plane in the CIP frame (M07 Step 5, FR-M07-03).

``bat_angle`` is the bat's orientation relative to vertical, measured in the
CIP frame (Book 4 Ch. 2: Y up, origin at the stance point). Sign convention:

- 0 deg  — bat straight up (a raised backlift),
- +90    — blade pointing along +X,
- -90    — blade pointing along -X,
- 180    — bat pointing straight down (address position).

The angle is computed from handle_bottom -> blade_tip, i.e. the blade's own
direction, not the handle's — the handle is short and its two points are close
together, so small pixel errors there swing the angle wildly. It is reported as
DERIVED: it comes from two detected points rather than being observed, and
carries the weaker of their confidences.

``swing_plane`` is the plane the bat sweeps through across the stroke, fitted
over the blade-tip positions by total least squares (the principal axis of
their spread). It is derived from the whole track, so it is the least direct
quantity M07 produces and is labelled accordingly. Two honesty rules:

- fewer than :data:`MIN_PLANE_FRAMES` tracked frames yields no plane at all,
  because a line through two points is not evidence of a plane;
- a track whose points barely spread (a bat that never moved, or a jittery
  detection cloud) yields no plane either — :data:`MIN_PLANE_SPREAD` — since
  the fit direction would be noise dressed as geometry.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    PROVENANCE_DERIVED,
    BatFrame,
)

#: A plane needs a real arc behind it, not two points and hope.
MIN_PLANE_FRAMES = 3
#: Minimum spread (CIP units) along the fitted axis for the plane to mean
#: anything. Below this the bat effectively did not move.
MIN_PLANE_SPREAD = 0.05


@dataclass(frozen=True, slots=True)
class BatAngle:
    """Per-frame bat orientation. Always derived, never measured."""

    frame_index: int
    degrees: float
    confidence: float
    provenance: str = PROVENANCE_DERIVED


@dataclass(frozen=True, slots=True)
class SwingPlane:
    """Principal axis of the blade's travel, as a unit vector in the CIP frame.

    ``inclination_degrees`` is that axis measured from vertical, the same
    convention as :class:`BatAngle`, so a near-vertical swing plane and a
    near-vertical bat read alike.
    """

    x: float
    y: float
    inclination_degrees: float
    #: How tightly the points hug the axis: 1.0 is a perfect line, 0.0 a blob.
    linearity: float
    confidence: float
    provenance: str = PROVENANCE_DERIVED


def bat_angle(frame: BatFrame) -> BatAngle | None:
    """Angle of the blade from vertical, in the CIP frame (Y up).

    Returns None when either endpoint is missing or the two points coincide —
    a zero-length blade has no direction, and 0 degrees would be a lie.
    """
    shoulder = frame.part(HANDLE_BOTTOM)
    tip = frame.part(BLADE_TIP)
    if shoulder is None or tip is None:
        return None

    dx = tip.x - shoulder.x
    dy = tip.y - shoulder.y
    if math.isclose(dx, 0.0, abs_tol=1e-9) and math.isclose(dy, 0.0, abs_tol=1e-9):
        return None

    # atan2(dx, dy) rather than (dy, dx): angle is measured FROM vertical,
    # so +Y is the zero direction and +X is +90.
    degrees = math.degrees(math.atan2(dx, dy))
    return BatAngle(
        frame_index=frame.frame_index,
        degrees=degrees,
        confidence=min(shoulder.confidence, tip.confidence),
    )


def bat_angles(frames: tuple[BatFrame, ...]) -> tuple[BatAngle, ...]:
    """Angles for every frame where the blade was located."""
    angles = [bat_angle(f) for f in frames if f.detected]
    return tuple(a for a in angles if a is not None)


def _blade_tips(frames: tuple[BatFrame, ...]) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    for frame in frames:
        if not frame.detected:
            continue
        tip = frame.part(BLADE_TIP)
        if tip is not None:
            points.append((tip.x, tip.y, tip.confidence))
    return points


def swing_plane(frames: tuple[BatFrame, ...]) -> SwingPlane | None:
    """Fit the swing plane to the blade's path across the stroke.

    Total least squares on the tip positions: the principal axis of their
    covariance. Ordinary least squares would be wrong here — it minimises
    error in y only, so a near-vertical swing (very common: that is what a
    straight bat looks like side-on) would blow up.
    """
    points = _blade_tips(frames)
    if len(points) < MIN_PLANE_FRAMES:
        return None

    n = float(len(points))
    mean_x = sum(p[0] for p in points) / n
    mean_y = sum(p[1] for p in points) / n

    sxx = sum((p[0] - mean_x) ** 2 for p in points) / n
    syy = sum((p[1] - mean_y) ** 2 for p in points) / n
    sxy = sum((p[0] - mean_x) * (p[1] - mean_y) for p in points) / n

    # Eigenvalues of the 2x2 covariance matrix; the larger one's eigenvector
    # is the axis the points spread along.
    trace = sxx + syy
    diff = math.sqrt(max((sxx - syy) ** 2 + 4.0 * sxy * sxy, 0.0))
    major = (trace + diff) / 2.0
    minor = (trace - diff) / 2.0

    spread = math.sqrt(max(major, 0.0))
    if spread < MIN_PLANE_SPREAD:
        # The bat did not really travel; any direction here would be noise.
        return None

    if math.isclose(sxy, 0.0, abs_tol=1e-12):
        # Axis-aligned: pick whichever axis carries the larger variance.
        vx, vy = (1.0, 0.0) if sxx >= syy else (0.0, 1.0)
    else:
        vx, vy = (major - syy, sxy)
        length = math.hypot(vx, vy)
        vx, vy = vx / length, vy / length

    # Orient consistently (upward-ish) so the same swing never reports as its
    # own negation between runs.
    if vy < 0.0 or (math.isclose(vy, 0.0, abs_tol=1e-12) and vx < 0.0):
        vx, vy = -vx, -vy

    linearity = 1.0 - (math.sqrt(max(minor, 0.0)) / spread if spread > 0 else 0.0)
    mean_confidence = sum(p[2] for p in points) / n
    return SwingPlane(
        x=vx,
        y=vy,
        inclination_degrees=math.degrees(math.atan2(vx, vy)),
        linearity=max(0.0, min(1.0, linearity)),
        # A plane fitted from derived points is weaker than those points, and
        # weaker still when they scatter: linearity carries that through.
        confidence=mean_confidence * max(0.0, min(1.0, linearity)),
    )
