"""Unit tests for coordinate normalisation (M06 Step 4, Book 4 Ch. 2, AC-M06-03)."""

from __future__ import annotations

from pose_service.domain.keypoints import CANONICAL_JOINTS, Keypoint
from pose_service.domain.model import FakePoseModel
from pose_service.domain.normalise import normalise
from pose_service.domain.tracking import select_primary_subject


def _tracked_frames(width: int, height: int):
    model = FakePoseModel()
    detections = model.infer(frame_count=6, width=width, height=height)
    return select_primary_subject(detections, width=float(width)).frames


def _by_joint(frame: tuple[Keypoint, ...]) -> dict[str, Keypoint]:
    return {k.joint: k for k in frame}


class TestOriginAndAxes:
    def test_origin_at_ankle_midpoint_gives_ankles_near_zero(self) -> None:
        frames = _tracked_frames(1920, 1080)
        result = normalise(frames, frame_height=1080)
        first = _by_joint(result.frames[0])
        # Ankles sit at the origin -> their normalised y is ~0.
        assert abs(first["left_ankle"].y) < 0.02
        assert abs(first["right_ankle"].y) < 0.02

    def test_y_axis_points_up(self) -> None:
        frames = _tracked_frames(1920, 1080)
        result = normalise(frames, frame_height=1080)
        first = _by_joint(result.frames[0])
        # The nose is above the ankles in the world -> positive Y after flip.
        assert first["nose"].y > first["left_hip"].y > 0

    def test_all_2d_keypoints_present(self) -> None:
        frames = _tracked_frames(1920, 1080)
        result = normalise(frames, frame_height=1080)
        for f in result.frames:
            assert [k.joint for k in f] == list(CANONICAL_JOINTS)
            assert all(k.z is None for k in f)  # fake model is 2D
        assert result.depth_estimated is False


class TestResolutionIndependence:
    def test_same_setup_normalises_the_same_at_different_resolutions(self) -> None:
        # Same fake motion, different frame sizes -> near-identical normalised coords.
        hd = normalise(_tracked_frames(1280, 720), frame_height=720)
        fhd = normalise(_tracked_frames(1920, 1080), frame_height=1080)
        a = _by_joint(hd.frames[0])
        b = _by_joint(fhd.frames[0])
        for joint in ("nose", "left_wrist", "right_knee"):
            assert abs(a[joint].x - b[joint].x) < 0.02
            assert abs(a[joint].y - b[joint].y) < 0.02


class TestDepth:
    def test_z_carried_and_flagged_when_present(self) -> None:
        # A synthetic frame WITH a z value -> normalised z + depth_estimated true.
        frame = (
            Keypoint(joint="left_ankle", x=900, y=1000, confidence=0.9),
            Keypoint(joint="right_ankle", x=1000, y=1000, confidence=0.9),
            Keypoint(joint="nose", x=950, y=500, confidence=0.9, z=200.0, depth_estimated=True),
        )
        result = normalise((frame,), frame_height=1000, depth_estimated=True)
        nose = _by_joint(result.frames[0])["nose"]
        assert nose.z is not None
        assert nose.depth_estimated is True
        assert result.depth_estimated is True
