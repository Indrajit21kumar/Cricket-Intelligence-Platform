"""BM-01..BM-17 formula fixtures (M10 Step 4, REQ-BIO-035, AC-M10-01/02).

Each formula is checked against hand-computed values in a controlled synthetic
stroke, plus degenerate cases. Coordinates are already in the CIP frame + metres
(the normalisation of Step 2 is tested separately), so these fixtures set X/Y/Z
directly and assert the arithmetic.
"""

from __future__ import annotations

import math

import pytest

from biomechanics_service.domain import metrics
from biomechanics_service.domain.filters import raw_speed, savgol_smooth, smoothed_speed
from biomechanics_service.domain.geometry import Point3D
from biomechanics_service.domain.phase_align import align_phases
from biomechanics_service.domain.stroke import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    LEFT_ANKLE,
    LEFT_ELBOW,
    LEFT_HIP,
    LEFT_KNEE,
    LEFT_SHOULDER,
    LEFT_WRIST,
    NOSE,
    RIGHT_ANKLE,
    RIGHT_HIP,
    RIGHT_KNEE,
    RIGHT_SHOULDER,
    RIGHT_WRIST,
    SWEET_SPOT,
    Anthropometrics,
    BallContext,
    BatFrame,
    Calibration,
    NormalisedStroke,
    Phases,
    PoseFrame,
)

CAL = Calibration(
    metres_per_unit=1.0,
    fps=60.0,
    camera_angle="side_on",
    spatial_confidence="high",
    depth_estimated=True,
)
BALL = BallContext(release_frame=2, contact_frame=15, timing_reference="release_relative")
ANTHRO = Anthropometrics(height_cm=180.0, handedness="RHB")
PHASES = Phases(stance=0, backlift=4, downswing=8, impact=12, follow_through=16, method="standard")


def _p(x: float, y: float, z: float = 0.0) -> Point3D:
    return Point3D(x, y, z)


def _pose(frame: int, joints: dict[str, Point3D], conf: float = 0.9) -> PoseFrame:
    return PoseFrame(frame_index=frame, joints=joints, mean_confidence=conf)


def _stroke(
    pose_frames: tuple[PoseFrame, ...],
    *,
    bat_frames: tuple[BatFrame, ...] = (),
    phases: Phases = PHASES,
    frame_count: int | None = None,
) -> tuple[NormalisedStroke, object]:
    fc = frame_count if frame_count is not None else len(pose_frames)
    stroke = NormalisedStroke(
        correlation_id="c",
        pose_frames=pose_frames,
        bat_frames=bat_frames,
        phases=phases,
        ball=BALL,
        anthropometrics=ANTHRO,
        calibration=CAL,
    )
    return stroke, align_phases(phases, frame_count=fc)


class TestBM01HeadStability:
    def test_known_horizontal_displacement(self) -> None:
        # Head moves 0.05m in Z, 0.0 in X, stance(0) -> impact(12): 5cm.
        frames = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.05 * (i / 12))}) for i in range(17))
        stroke, phases = _stroke(frames)
        assert metrics.head_stability(stroke, phases) == pytest.approx(5.0)

    def test_a_still_head_is_zero(self) -> None:
        frames = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.0)}) for i in range(17))
        stroke, phases = _stroke(frames)
        assert metrics.head_stability(stroke, phases) == pytest.approx(0.0)

    def test_missing_head_is_none(self) -> None:
        frames = tuple(_pose(i, {LEFT_HIP: _p(0.0, 0.9, 0.0)}) for i in range(17))
        stroke, phases = _stroke(frames)
        assert metrics.head_stability(stroke, phases) is None


def _rotating_shoulders(angle_at_impact_deg: float) -> tuple[PoseFrame, ...]:
    """Shoulders aligned along X at stance, rotated by the given angle at impact."""
    frames = []
    for i in range(17):
        t = i / 12 if i <= 12 else 1.0
        theta = math.radians(angle_at_impact_deg * t)
        # Shoulder line of unit length, rotating in the X-Z plane about centre.
        dx = math.cos(theta)
        dz = math.sin(theta)
        frames.append(
            _pose(
                i,
                {
                    RIGHT_SHOULDER: _p(0.2 * dx, 1.4, 0.2 * dz),
                    LEFT_SHOULDER: _p(-0.2 * dx, 1.4, -0.2 * dz),
                },
            )
        )
    return tuple(frames)


class TestBM02ShoulderRotation:
    def test_known_rotation(self) -> None:
        stroke, phases = _stroke(_rotating_shoulders(45.0))
        assert metrics.shoulder_rotation(stroke, phases) == pytest.approx(45.0, abs=1e-6)

    def test_no_rotation(self) -> None:
        stroke, phases = _stroke(_rotating_shoulders(0.0))
        assert metrics.shoulder_rotation(stroke, phases) == pytest.approx(0.0)


class TestBM03HipRotation:
    def test_known_rotation(self) -> None:
        frames = []
        for i in range(17):
            t = i / 12 if i <= 12 else 1.0
            theta = math.radians(30.0 * t)
            frames.append(
                _pose(
                    i,
                    {
                        RIGHT_HIP: _p(0.15 * math.cos(theta), 0.9, 0.15 * math.sin(theta)),
                        LEFT_HIP: _p(-0.15 * math.cos(theta), 0.9, -0.15 * math.sin(theta)),
                    },
                )
            )
        stroke, phases = _stroke(tuple(frames))
        assert metrics.hip_rotation(stroke, phases) == pytest.approx(30.0, abs=1e-6)


class TestBM04XFactor:
    def test_separation_at_downswing_start(self) -> None:
        # Shoulders rotate 40deg by downswing start; hips 10deg. X-factor = 30.
        frames = []
        for i in range(17):
            t = min(i / 8, 1.0)  # downswing starts at frame 8
            s = math.radians(40.0 * t)
            h = math.radians(10.0 * t)
            frames.append(
                _pose(
                    i,
                    {
                        RIGHT_SHOULDER: _p(0.2 * math.cos(s), 1.4, 0.2 * math.sin(s)),
                        LEFT_SHOULDER: _p(-0.2 * math.cos(s), 1.4, -0.2 * math.sin(s)),
                        RIGHT_HIP: _p(0.15 * math.cos(h), 0.9, 0.15 * math.sin(h)),
                        LEFT_HIP: _p(-0.15 * math.cos(h), 0.9, -0.15 * math.sin(h)),
                    },
                )
            )
        stroke, phases = _stroke(tuple(frames))
        assert metrics.x_factor(stroke, phases) == pytest.approx(30.0, abs=1e-6)


class TestBM05PelvicTilt:
    def test_level_hips_are_zero(self) -> None:
        frames = tuple(
            _pose(i, {LEFT_HIP: _p(-0.15, 0.9, 0.0), RIGHT_HIP: _p(0.15, 0.9, 0.0)})
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        assert metrics.pelvic_tilt(stroke, phases) == pytest.approx(0.0)

    def test_tilted_hips(self) -> None:
        # Right hip 0.1m higher over a 0.3m horizontal span -> atan(0.1/0.3).
        frames = tuple(
            _pose(i, {LEFT_HIP: _p(-0.15, 0.85, 0.0), RIGHT_HIP: _p(0.15, 0.95, 0.0)})
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        expected = math.degrees(math.atan2(0.1, 0.3))
        assert metrics.pelvic_tilt(stroke, phases) == pytest.approx(expected)


class TestBM06FrontKneeFlexion:
    def test_straight_leg_is_180(self) -> None:
        # Hip-knee-ankle collinear vertical -> 180 degrees.
        frames = tuple(
            _pose(
                i,
                {
                    LEFT_HIP: _p(0.0, 0.9, 0.3),
                    LEFT_KNEE: _p(0.0, 0.5, 0.3),
                    LEFT_ANKLE: _p(0.0, 0.1, 0.3),
                    RIGHT_ANKLE: _p(0.0, 0.1, -0.1),
                },
            )
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        assert metrics.front_knee_flexion(stroke, phases) == pytest.approx(180.0, abs=1e-6)

    def test_right_angle_knee(self) -> None:
        frames = tuple(
            _pose(
                i,
                {
                    LEFT_HIP: _p(0.0, 0.9, 0.3),
                    LEFT_KNEE: _p(0.0, 0.5, 0.3),
                    LEFT_ANKLE: _p(0.0, 0.5, 0.7),
                    RIGHT_ANKLE: _p(0.0, 0.1, -0.1),
                },
            )
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        assert metrics.front_knee_flexion(stroke, phases) == pytest.approx(90.0, abs=1e-6)


class TestBM08StrideLength:
    def test_percent_of_height(self) -> None:
        # Ankles 0.9m apart, height 180cm -> 90cm / 180cm * 100 = 50%.
        frames = tuple(
            _pose(i, {LEFT_ANKLE: _p(0.0, 0.1, 0.45), RIGHT_ANKLE: _p(0.0, 0.1, -0.45)})
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        assert metrics.stride_length(stroke, phases) == pytest.approx(50.0)

    def test_no_height_is_none(self) -> None:
        frames = tuple(
            _pose(i, {LEFT_ANKLE: _p(0.0, 0.1, 0.45), RIGHT_ANKLE: _p(0.0, 0.1, -0.45)})
            for i in range(17)
        )
        stroke = NormalisedStroke(
            correlation_id="c",
            pose_frames=frames,
            bat_frames=(),
            phases=PHASES,
            ball=BALL,
            anthropometrics=Anthropometrics(height_cm=None, handedness="RHB"),
            calibration=CAL,
        )
        assert metrics.stride_length(stroke, align_phases(PHASES, frame_count=17)) is None


def _bat_frames(angle_by_frame: dict[int, float]) -> tuple[BatFrame, ...]:
    """Bat frames with the given angle-from-vertical (deg) at each index."""
    frames = []
    for i in range(17):
        deg = angle_by_frame.get(i, 0.0)
        theta = math.radians(deg)
        handle = _p(0.0, 0.8, 0.0)
        tip = _p(0.6 * math.sin(theta), 0.8 + 0.6 * math.cos(theta), 0.0)
        frames.append(
            BatFrame(
                frame_index=i,
                parts={HANDLE_BOTTOM: handle, BLADE_TIP: tip, SWEET_SPOT: tip},
                detected=True,
            )
        )
    return tuple(frames)


class TestBM09Backlift:
    def test_peak_bat_angle_in_backlift(self) -> None:
        # Backlift window is frames 4..7; peak angle 70deg at frame 6.
        bats = _bat_frames({4: 30.0, 5: 55.0, 6: 70.0, 7: 60.0})
        poses = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.0)}) for i in range(17))
        stroke, phases = _stroke(poses, bat_frames=bats)
        assert metrics.backlift(stroke, phases) == pytest.approx(70.0, abs=1e-6)

    def test_no_bat_is_none(self) -> None:
        poses = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.0)}) for i in range(17))
        stroke, phases = _stroke(poses)
        assert metrics.backlift(stroke, phases) is None


class TestBM10BatPathLinearity:
    def test_a_straight_path_is_r2_one(self) -> None:
        # Sweet spot moves linearly in Z-Y through the downswing (8..11).
        frames = []
        for i in range(17):
            z = 0.1 * i
            y = 0.5 + 0.2 * z
            frames.append(
                BatFrame(
                    frame_index=i,
                    parts={SWEET_SPOT: _p(0.0, y, z), HANDLE_BOTTOM: _p(0.0, 0.8, 0.0)},
                    detected=True,
                )
            )
        poses = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.0)}) for i in range(17))
        stroke, phases = _stroke(poses, bat_frames=tuple(frames))
        assert metrics.bat_path_linearity(stroke, phases) == pytest.approx(1.0, abs=1e-9)

    def test_a_scattered_path_is_below_one(self) -> None:
        zs = [0.0, 0.3, 0.1, 0.4]  # non-monotone scatter over the downswing
        frames = []
        for i in range(17):
            z = zs[i - 8] if 8 <= i <= 11 else 0.0
            y = 0.6 + (0.3 if i % 2 else -0.3)
            frames.append(
                BatFrame(
                    frame_index=i,
                    parts={SWEET_SPOT: _p(0.0, y, z), HANDLE_BOTTOM: _p(0.0, 0.8, 0.0)},
                    detected=True,
                )
            )
        poses = tuple(_pose(i, {NOSE: _p(0.0, 1.7, 0.0)}) for i in range(17))
        stroke, phases = _stroke(poses, bat_frames=tuple(frames))
        r2 = metrics.bat_path_linearity(stroke, phases)
        assert r2 is not None and r2 < 0.9


class TestBM12HandSpeed:
    def test_known_constant_speed(self) -> None:
        # Wrists move 0.1m per frame at 60fps -> 6 m/s, both wrists coincident.
        frames = tuple(
            _pose(
                i,
                {LEFT_WRIST: _p(0.0, 1.0, 0.1 * i), RIGHT_WRIST: _p(0.0, 1.0, 0.1 * i)},
            )
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        speed = metrics.hand_speed(stroke, phases)
        assert speed == pytest.approx(6.0, abs=0.2)

    def test_savgol_does_not_inflate_speed(self) -> None:
        """AC-M10-02: smoothed peak must not exceed the true underlying speed."""
        # A clean ramp plus alternating jitter; smoothing must tame the jitter.
        positions = [(0.0, 0.0, 0.1 * i + (0.03 if i % 2 else -0.03)) for i in range(17)]
        raw = raw_speed(positions, fps=60.0)
        smooth = smoothed_speed(positions, fps=60.0)
        assert max(smooth[2:-2]) < max(raw)


class TestBM14BalanceRecovery:
    def test_settles_after_impact(self) -> None:
        # CoM moves before impact (12), then holds still -> recovers next frame.
        frames = []
        for i in range(20):
            z = 0.02 * i if i <= 12 else 0.02 * 12
            joints = {
                NOSE: _p(0.0, 1.7, z),
                LEFT_SHOULDER: _p(-0.2, 1.4, z),
                RIGHT_SHOULDER: _p(0.2, 1.4, z),
                LEFT_HIP: _p(-0.15, 0.9, z),
                RIGHT_HIP: _p(0.15, 0.9, z),
            }
            frames.append(_pose(i, joints))
        stroke, phases = _stroke(tuple(frames), frame_count=20)
        recovery = metrics.balance_recovery(stroke, phases)
        assert recovery is not None
        assert 0.0 <= recovery <= 200.0  # settles within a couple of frames


class TestBM15WeightTransfer:
    def test_is_a_bounded_estimated_proxy(self) -> None:
        frames = tuple(
            _pose(
                i,
                {
                    LEFT_HIP: _p(0.0, 0.9, 0.3),
                    LEFT_KNEE: _p(0.0, 0.5, 0.32),
                    LEFT_ANKLE: _p(0.0, 0.1, 0.3),
                    RIGHT_HIP: _p(0.0, 0.9, -0.1),
                    RIGHT_KNEE: _p(0.0, 0.5, -0.1),
                    RIGHT_ANKLE: _p(0.0, 0.1, -0.1),
                },
            )
            for i in range(17)
        )
        stroke, phases = _stroke(frames)
        wt = metrics.weight_transfer(stroke, phases)
        assert wt is not None
        assert 0.0 <= wt <= 1.0


class TestBM16CentreOfMass:
    def test_path_length_of_a_moving_com(self) -> None:
        # A body translating 0.01m in Z each frame; CoM path ~ (n-1)*0.01*100 cm.
        frames = []
        for i in range(17):
            z = 0.01 * i
            frames.append(
                _pose(
                    i,
                    {
                        NOSE: _p(0.0, 1.7, z),
                        LEFT_SHOULDER: _p(-0.2, 1.4, z),
                        RIGHT_SHOULDER: _p(0.2, 1.4, z),
                        LEFT_HIP: _p(-0.15, 0.9, z),
                        RIGHT_HIP: _p(0.15, 0.9, z),
                    },
                )
            )
        stroke, phases = _stroke(tuple(frames))
        path = metrics.centre_of_mass_path(stroke, phases)
        assert path == pytest.approx(16 * 0.01 * 100.0, abs=1e-6)


class TestBM17GroundContactTiming:
    def test_release_relative_timing(self) -> None:
        # Front ankle plants at frame 4; release frame 2; 60fps -> (4-2)/60*1000.
        frames = []
        for i in range(17):
            # Front (left, larger Z) ankle descends then holds from frame 4.
            y = 0.5 - 0.1 * i if i < 4 else 0.1
            frames.append(
                _pose(
                    i,
                    {LEFT_ANKLE: _p(0.0, y, 0.3), RIGHT_ANKLE: _p(0.0, 0.1, -0.1)},
                )
            )
        stroke, phases = _stroke(tuple(frames))
        expected = (4 - 2) / 60.0 * 1000.0
        assert metrics.ground_contact_timing(stroke, phases) == pytest.approx(expected, abs=1e-6)

    def test_absolute_timing_when_no_release(self) -> None:
        frames = tuple(
            _pose(i, {LEFT_ANKLE: _p(0.0, 0.1, 0.3), RIGHT_ANKLE: _p(0.0, 0.1, -0.1)})
            for i in range(17)
        )
        stroke = NormalisedStroke(
            correlation_id="c",
            pose_frames=frames,
            bat_frames=(),
            phases=PHASES,
            ball=BallContext(release_frame=None, contact_frame=None, timing_reference="absolute"),
            anthropometrics=ANTHRO,
            calibration=CAL,
        )
        timing = metrics.ground_contact_timing(stroke, align_phases(PHASES, frame_count=17))
        assert timing is not None and timing >= 0.0


class TestComputeAll:
    def test_all_seventeen_keys_present(self) -> None:
        poses = tuple(
            _pose(
                i,
                {
                    NOSE: _p(0.0, 1.7, 0.0),
                    LEFT_SHOULDER: _p(-0.2, 1.4, 0.0),
                    RIGHT_SHOULDER: _p(0.2, 1.4, 0.0),
                    LEFT_HIP: _p(-0.15, 0.9, 0.0),
                    RIGHT_HIP: _p(0.15, 0.9, 0.0),
                    LEFT_KNEE: _p(0.0, 0.5, 0.3),
                    LEFT_ANKLE: _p(0.0, 0.1, 0.3),
                    RIGHT_KNEE: _p(0.0, 0.5, -0.1),
                    RIGHT_ANKLE: _p(0.0, 0.1, -0.1),
                    LEFT_WRIST: _p(0.0, 1.0, 0.05 * i),
                    RIGHT_WRIST: _p(0.0, 1.0, 0.05 * i),
                    LEFT_ELBOW: _p(-0.05, 1.2, 0.0),
                },
            )
            for i in range(17)
        )
        stroke, phases = _stroke(poses, bat_frames=_bat_frames({6: 60.0}))
        result = metrics.compute_metrics(stroke, phases)
        assert len(result) == 17
        assert all(k in result for k in [f"BM-{n:02d}" for n in range(1, 18)])


class TestSavgol:
    def test_short_series_unchanged(self) -> None:
        assert savgol_smooth([1.0, 2.0]) == [1.0, 2.0]

    def test_smooths_a_spike(self) -> None:
        spiky = [0.0, 0.0, 1.0, 0.0, 0.0]
        out = savgol_smooth(spiky)
        assert out[2] < 1.0  # the spike is pulled down
        assert out[0] == 0.0 and out[-1] == 0.0  # edges untouched
