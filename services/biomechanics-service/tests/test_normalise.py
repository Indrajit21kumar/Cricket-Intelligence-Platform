"""Coordinate normalisation + handedness mirroring (M10 Step 2, FR-M10-02, AC-M10-05).

The load-bearing test is `test_lhb_mirror_invariance`: a left-hander's stroke,
which is the mirror image of the right-hander's, must produce IDENTICAL
normalised coordinates - so every downstream formula and benchmark is
handedness-agnostic with no special-casing.
"""

from __future__ import annotations

import pytest

from biomechanics_service.domain.builder import (
    RawBatFrame,
    RawPoseFrame,
    RawStroke,
    build_normalised_stroke,
)
from biomechanics_service.domain.normalise import is_supported_angle, to_cip
from biomechanics_service.domain.stroke import (
    ANGLE_FRONT_ON,
    ANGLE_SIDE_ON,
    LHB,
    RHB,
    Anthropometrics,
    BallContext,
    Calibration,
    Phases,
)

PHASES = Phases(stance=0, backlift=5, downswing=10, impact=15, follow_through=20, method="standard")
BALL = BallContext(release_frame=2, contact_frame=15, timing_reference="release_relative")


def _calibration(angle: str = ANGLE_SIDE_ON, mpu: float | None = 2.0) -> Calibration:
    return Calibration(
        metres_per_unit=mpu,
        fps=60.0,
        camera_angle=angle,
        spatial_confidence="high",
        depth_estimated=True,
    )


class TestAxisMapping:
    def test_side_on_maps_image_x_to_down_pitch_z(self) -> None:
        """Side-on sees down the pitch, so image-x is Z; crease X is depth."""
        p = to_cip(0.3, 0.8, camera_angle=ANGLE_SIDE_ON, metres_per_unit=2.0, handedness=RHB)
        assert p.z == pytest.approx(0.6)  # 0.3 * 2.0
        assert p.y == pytest.approx(1.6)  # 0.8 * 2.0
        assert p.x == 0.0
        assert p.depth_estimated is True

    def test_front_on_maps_image_x_to_crease_x(self) -> None:
        """Front-on sees the crease, so image-x is X; down-pitch Z is depth."""
        p = to_cip(0.3, 0.8, camera_angle=ANGLE_FRONT_ON, metres_per_unit=2.0, handedness=RHB)
        assert p.x == pytest.approx(0.6)
        assert p.y == pytest.approx(1.6)
        assert p.z == 0.0
        assert p.depth_estimated is True

    def test_scale_converts_to_metres(self) -> None:
        p = to_cip(0.5, 0.5, camera_angle=ANGLE_FRONT_ON, metres_per_unit=3.2, handedness=RHB)
        assert p.x == pytest.approx(1.6)

    def test_supported_angles(self) -> None:
        assert is_supported_angle(ANGLE_SIDE_ON)
        assert is_supported_angle(ANGLE_FRONT_ON)
        assert not is_supported_angle("square")


class TestHandednessMirror:
    def test_rhb_is_pass_through(self) -> None:
        p = to_cip(0.4, 0.7, camera_angle=ANGLE_FRONT_ON, metres_per_unit=1.0, handedness=RHB)
        assert p.x == pytest.approx(0.4)

    def test_lhb_negates_the_crease_axis(self) -> None:
        p = to_cip(0.4, 0.7, camera_angle=ANGLE_FRONT_ON, metres_per_unit=1.0, handedness=LHB)
        assert p.x == pytest.approx(-0.4)
        assert p.y == pytest.approx(0.7)  # vertical untouched


def _raw(handedness: str, x_sign: float, angle: str = ANGLE_FRONT_ON) -> RawStroke:
    """A one-frame stroke whose crease-axis positions are flipped by x_sign."""
    return RawStroke(
        correlation_id="c-mirror",
        pose=(
            RawPoseFrame(
                frame_index=0,
                joints={
                    "right_shoulder": (x_sign * 0.3, 1.4, 0.9),
                    "left_shoulder": (x_sign * 0.1, 1.4, 0.9),
                    "right_hip": (x_sign * 0.2, 0.9, 0.9),
                },
            ),
        ),
        bat=(RawBatFrame(frame_index=0, detected=True, parts={"blade_tip": (x_sign * 0.5, 0.3)}),),
        phases=PHASES,
        ball=BALL,
        anthropometrics=Anthropometrics(height_cm=180.0, handedness=handedness),
        calibration=_calibration(angle),
    )


class TestMirrorInvariance:
    def test_lhb_mirror_invariance(self) -> None:
        """AC-M10-05: an LHB stroke mirror-images an RHB one, yet normalises the same.

        The RHB stroke has keypoints on +X; the physically-mirrored LHB stroke
        has them on -X. After the handedness mirror, both land on the same
        normalised coordinates, so downstream logic never branches on handedness.
        """
        rhb = build_normalised_stroke(_raw(RHB, x_sign=1.0))
        lhb = build_normalised_stroke(_raw(LHB, x_sign=-1.0))

        for joint in ("right_shoulder", "left_shoulder", "right_hip"):
            r = rhb.pose_frames[0].get(joint)
            m = lhb.pose_frames[0].get(joint)
            assert r is not None and m is not None
            assert m.x == pytest.approx(r.x)
            assert m.y == pytest.approx(r.y)

        r_bat = rhb.bat_frames[0].get("blade_tip")
        m_bat = lhb.bat_frames[0].get("blade_tip")
        assert r_bat is not None and m_bat is not None
        assert m_bat.x == pytest.approx(r_bat.x)


class TestStrokeAssembly:
    def test_bat_detected_frames_are_recorded(self) -> None:
        raw = RawStroke(
            correlation_id="c1",
            pose=(RawPoseFrame(frame_index=0, joints={"nose": (0.0, 1.6, 0.9)}),),
            bat=(
                RawBatFrame(frame_index=0, detected=True, parts={"blade_tip": (0.1, 0.3)}),
                RawBatFrame(frame_index=1, detected=False),
            ),
            phases=PHASES,
            ball=BALL,
            anthropometrics=Anthropometrics(height_cm=175.0, handedness=RHB),
            calibration=_calibration(),
        )
        stroke = build_normalised_stroke(raw)
        assert stroke.bat_detected_frames == frozenset({0})
        assert stroke.frame_count == 1

    def test_mean_pose_confidence_per_frame(self) -> None:
        raw = RawStroke(
            correlation_id="c2",
            pose=(
                RawPoseFrame(
                    frame_index=0,
                    joints={"nose": (0.0, 1.6, 0.8), "left_hip": (0.0, 0.9, 0.6)},
                ),
            ),
            bat=(),
            phases=PHASES,
            ball=BALL,
            anthropometrics=Anthropometrics(height_cm=175.0, handedness=RHB),
            calibration=_calibration(),
        )
        stroke = build_normalised_stroke(raw)
        assert stroke.pose_frames[0].mean_confidence == pytest.approx(0.7)

    def test_missing_scale_keeps_frame_height_units(self) -> None:
        """No calibration -> coords stay unit-scaled; Step 5 flags the run."""
        base = _raw(RHB, x_sign=1.0, angle=ANGLE_FRONT_ON)
        raw = RawStroke(
            correlation_id=base.correlation_id,
            pose=base.pose,
            bat=base.bat,
            phases=base.phases,
            ball=base.ball,
            anthropometrics=base.anthropometrics,
            # Front-on so image-x maps to the crease X we assert on.
            calibration=_calibration(angle=ANGLE_FRONT_ON, mpu=None),
        )
        stroke = build_normalised_stroke(raw)
        shoulder = stroke.pose_frames[0].get("right_shoulder")
        assert shoulder is not None
        assert shoulder.x == pytest.approx(0.3)  # unscaled (mpu fell back to 1.0)
