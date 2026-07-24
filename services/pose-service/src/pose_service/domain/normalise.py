"""Coordinate normalisation to the CIP frame (M06 Step 4, Book 4 Ch. 2, AC-M06-03).

Raw model keypoints are pixels with Y pointing DOWN. Book 4 §2.1 defines a
normalised batting frame:

- Origin: the ground point beneath mid-stance — the ankle midpoint in the
  first frame the subject appears (the stance frame).
- Y: vertical, positive UP (so we flip the pixel Y).
- X: along the crease. M06 emits X in image space and does NOT mirror for
  left-handers — handedness mirroring is applied downstream by M10 (M06 §5),
  keeping this stage a pure geometric transform.
- Scale: divided by the frame height so coordinates are resolution-independent
  (the same physical setup gives the same numbers at 720p or 1080p). The
  pixel→cm calibration itself is M05's ``pixel_to_meter``, applied by M10.

Depth: M06's 2D keypoints are ALWAYS present. A z is emitted only if a
monocular 3D-lift produced one, and then the run is flagged
``depth_estimated`` (Book 4 §2.3) — the fake model is 2D, so z stays None.
"""

from __future__ import annotations

from dataclasses import dataclass

from pose_service.domain.keypoints import Keypoint


@dataclass(frozen=True, slots=True)
class NormalisedFrames:
    frames: tuple[tuple[Keypoint, ...], ...]
    origin_x: float
    origin_y: float
    depth_estimated: bool


def _kp(frame: tuple[Keypoint, ...], joint: str) -> Keypoint | None:
    for k in frame:
        if k.joint == joint:
            return k
    return None


def _origin(frames: tuple[tuple[Keypoint, ...], ...]) -> tuple[float, float] | None:
    """Ground point beneath mid-stance: ankle midpoint of the first present frame.

    Falls back to the hip midpoint if the ankles are absent.
    """
    for frame in frames:
        if not frame:
            continue
        la, ra = _kp(frame, "left_ankle"), _kp(frame, "right_ankle")
        if la is not None and ra is not None:
            return ((la.x + ra.x) / 2, (la.y + ra.y) / 2)
        lh, rh = _kp(frame, "left_hip"), _kp(frame, "right_hip")
        if lh is not None and rh is not None:
            return ((lh.x + rh.x) / 2, (lh.y + rh.y) / 2)
    return None


def normalise(
    frames: tuple[tuple[Keypoint, ...], ...],
    *,
    frame_height: int,
    depth_estimated: bool = False,
) -> NormalisedFrames:
    """Transform pixel keypoints into the CIP normalised frame (Y-up, origin at stance)."""
    origin = _origin(frames)
    if origin is None:
        return NormalisedFrames(
            frames=frames, origin_x=0.0, origin_y=0.0, depth_estimated=depth_estimated
        )
    ox, oy = origin
    scale = float(frame_height) if frame_height > 0 else 1.0

    out: list[tuple[Keypoint, ...]] = []
    for frame in frames:
        nf = tuple(
            Keypoint(
                joint=k.joint,
                x=(k.x - ox) / scale,  # X in image direction (mirroring is M10's job)
                y=(oy - k.y) / scale,  # flip to Y-up (Book 4 §2.1)
                confidence=k.confidence,
                z=(k.z / scale) if k.z is not None else None,
                depth_estimated=k.depth_estimated,
            )
            for k in frame
        )
        out.append(nf)
    return NormalisedFrames(
        frames=tuple(out), origin_x=ox, origin_y=oy, depth_estimated=depth_estimated
    )
