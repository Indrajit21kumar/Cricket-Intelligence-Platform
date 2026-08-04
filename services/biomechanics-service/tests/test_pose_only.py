"""Pose-First MVP: a report built from pose alone (no bat / ball / shot).

These are the acceptance tests for the pose-only path. They prove the two
things that matter: the body metrics are really computed, and nothing the
stub detectors would have supplied appears anywhere in the output.
"""

from __future__ import annotations

import math

import pytest

from biomechanics_service.domain.builder import RawPoseFrame
from biomechanics_service.domain.catalogue import (
    BAT_DEPENDENT_IDS,
    BM_02,
    BM_03,
    BM_04,
    BM_05,
    BM_06,
    BM_08,
)
from biomechanics_service.domain.pose_only import build_pose_only_stroke
from biomechanics_service.domain.pose_phases import PHASE_METHOD_POSE_WRIST
from biomechanics_service.domain.report import compute_report
from biomechanics_service.domain.stroke import (
    ANGLE_SIDE_ON,
    RHB,
    SPATIAL_HIGH,
    SPATIAL_LOW,
    Anthropometrics,
    Calibration,
)

FPS = 30.0

#: What monocular pose can ACTUALLY deliver.
#:
#: The MVP brief asked for six metrics. Three of them — BM-02 shoulder
#: rotation, BM-03 hip rotation and BM-04 X-Factor — are angles in the
#: TOP-DOWN plane, and a single camera cannot measure those: ``to_cip`` pins
#: one horizontal axis to exactly 0.0, so the top-down angle is a constant
#: (90 deg side-on, 0 deg otherwise) whether the batter is square or coiled
#: 45 deg. Their frame-to-frame "rotation" is therefore identically 0.0.
#: They are disabled with ``depth_unresolved`` rather than published as a
#: confident zero. BM-08 stride needs the crease axis, so it needs real
#: camera-angle detection. See TestDepthLimits below.
POSE_ONLY_IDS = (BM_05, BM_06)
#: Blocked until stereo capture or a monocular 3D lift exists.
DEPTH_BLOCKED_IDS = (BM_02, BM_03, BM_04)


def _frame(index: int, *, shoulder_deg: float, hip_deg: float, wrist_y: float) -> RawPoseFrame:
    """One frame of a right-hander rotating through a stroke.

    Shoulders and hips are drawn as lines rotating about the body centre by
    their own angle, so shoulder/hip rotation and their separation (X-Factor)
    are known by construction rather than by coincidence.
    """
    conf = 0.9
    cx, cy = 0.50, 0.50

    def line(half_width: float, deg: float, y: float) -> tuple[tuple[float, float], ...]:
        rad = math.radians(deg)
        dx, dz = half_width * math.cos(rad), half_width * math.sin(rad)
        # The z component projects onto image-y under a side-on camera.
        return ((cx - dx, y - dz * 0.1), (cx + dx, y + dz * 0.1))

    (lsx, lsy), (rsx, rsy) = line(0.10, shoulder_deg, cy + 0.16)
    (lhx, lhy), (rhx, rhy) = line(0.07, hip_deg, cy)

    return RawPoseFrame(
        frame_index=index,
        joints={
            "nose": (cx, cy + 0.26, conf),
            "left_shoulder": (lsx, lsy, conf),
            "right_shoulder": (rsx, rsy, conf),
            "left_elbow": (cx - 0.13, cy + 0.05, conf),
            "right_elbow": (cx + 0.13, cy + 0.05, conf),
            "left_wrist": (cx - 0.06, wrist_y, conf),
            "right_wrist": (cx + 0.02, wrist_y, conf),
            "left_hip": (lhx, lhy, conf),
            "right_hip": (rhx, rhy, conf),
            "left_knee": (cx - 0.08, cy - 0.20, conf),
            "right_knee": (cx + 0.08, cy - 0.22, conf),
            "left_ankle": (cx - 0.14, cy - 0.40, conf),
            "right_ankle": (cx + 0.10, cy - 0.42, conf),
        },
    )


def _stroke_pose() -> list[RawPoseFrame]:
    """Stance, backlift (shoulders coil ahead of hips), downswing, follow-through."""
    frames: list[RawPoseFrame] = []
    for i in range(10):  # stance
        frames.append(_frame(i, shoulder_deg=0.0, hip_deg=0.0, wrist_y=0.40))
    for i in range(15):  # backlift: shoulders turn further than hips
        t = (i + 1) / 15
        frames.append(
            _frame(10 + i, shoulder_deg=45.0 * t, hip_deg=15.0 * t, wrist_y=0.40 + 0.35 * t)
        )
    for i in range(15):  # downswing: hips lead back through
        t = (i + 1) / 15
        frames.append(
            _frame(
                25 + i,
                shoulder_deg=45.0 - 40.0 * t,
                hip_deg=15.0 - 20.0 * t,
                wrist_y=0.75 - 0.50 * t * t,
            )
        )
    for i in range(10):  # follow-through
        frames.append(_frame(40 + i, shoulder_deg=5.0, hip_deg=-5.0, wrist_y=0.25))
    return frames


def _calibration(*, side_on: bool = True) -> Calibration:
    return Calibration(
        metres_per_unit=None,  # no scale: the MVP ships angles, not distances
        fps=FPS,
        camera_angle=ANGLE_SIDE_ON if side_on else "other",
        spatial_confidence=SPATIAL_HIGH if side_on else SPATIAL_LOW,
        depth_estimated=True,
    )


def _report(*, side_on: bool = True):  # type: ignore[no-untyped-def]
    raw = build_pose_only_stroke(
        correlation_id="pose-only-1",
        pose=_stroke_pose(),
        calibration=_calibration(side_on=side_on),
        anthropometrics=Anthropometrics(height_cm=178.0, handedness=RHB),
    )
    return raw, compute_report(raw)


class TestNoFakeUpstreamReachesTheReport:
    """Rule 1: no bat/ball/shot value may appear in this path."""

    def test_bat_frames_are_empty_not_fabricated(self) -> None:
        raw, _ = _report()
        assert raw.bat == ()
        assert raw.bat_downswing_failure_ratio is None

    def test_no_shot_label_is_claimed(self) -> None:
        raw, report = _report()
        assert raw.shot_type is None
        assert report.shot_type is None
        assert report.shot_confidence is None

    def test_no_ball_anchors_are_claimed(self) -> None:
        raw, _ = _report()
        assert raw.ball.release_frame is None
        assert raw.ball.contact_frame is None

    @pytest.mark.parametrize("metric_id", BAT_DEPENDENT_IDS)
    def test_bat_dependent_metrics_are_omitted_never_guessed(self, metric_id: str) -> None:
        _, report = _report()
        mv = report.metrics[metric_id]
        assert mv.value is None, f"{metric_id} invented a value without a bat"
        assert mv.confidence == 0.0


class TestBodyMetricsAreReallyComputed:
    """Rule 2: the six shipped metrics carry real values."""

    @pytest.mark.parametrize("metric_id", POSE_ONLY_IDS)
    def test_metric_has_a_value(self, metric_id: str) -> None:
        _, report = _report()
        assert report.metrics[metric_id].value is not None, f"{metric_id} produced nothing"

    @pytest.mark.parametrize("metric_id", POSE_ONLY_IDS)
    def test_metric_carries_confidence_and_provenance(self, metric_id: str) -> None:
        _, report = _report()
        mv = report.metrics[metric_id]
        assert mv.confidence > 0.0
        assert mv.provenance

    def test_front_knee_flexion_is_a_plausible_angle(self) -> None:
        _, report = _report()
        value = report.metrics[BM_06].value
        assert value is not None
        assert 0.0 <= value <= 180.0


class TestDepthLimits:
    """A single camera cannot measure rotation about the vertical axis.

    The fixture genuinely coils the shoulders 45deg against 15deg of hip turn.
    A stereo rig would read ~30deg of separation. Monocular capture reads
    nothing at all — so the honest output is "not measurable", never 0.0.
    """

    @pytest.mark.parametrize("metric_id", DEPTH_BLOCKED_IDS)
    def test_rotation_metrics_are_disabled_not_reported_as_zero(self, metric_id: str) -> None:
        _, report = _report()
        mv = report.metrics[metric_id]
        assert mv.value is None, f"{metric_id} published a top-down angle from one camera"
        assert mv.disabled_reason == "depth_unresolved"
        assert mv.confidence == 0.0

    def test_the_underlying_formula_really_does_collapse(self) -> None:
        """Guards the reason for the gate, so it is not deleted as redundant."""
        from biomechanics_service.domain.metrics import _line_angle_topdown
        from biomechanics_service.domain.normalise import to_cip

        def shoulder_line(deg: float) -> float:
            rad = math.radians(deg)
            left = to_cip(
                0.5 - 0.1 * math.cos(rad),
                0.5 - 0.1 * math.sin(rad),
                camera_angle=ANGLE_SIDE_ON,
                metres_per_unit=1.0,
                handedness=RHB,
            )
            right = to_cip(
                0.5 + 0.1 * math.cos(rad),
                0.5 + 0.1 * math.sin(rad),
                camera_angle=ANGLE_SIDE_ON,
                metres_per_unit=1.0,
                handedness=RHB,
            )
            return _line_angle_topdown(left, right)

        assert shoulder_line(0.0) == shoulder_line(45.0)


class TestUncalibratedMetricsAreNotPublished:
    """No metric scale means no cm and no m/s — not a number in frame units."""

    @pytest.mark.parametrize("metric_id", ("BM-01", "BM-12", "BM-16"))
    def test_distance_and_velocity_metrics_are_disabled(self, metric_id: str) -> None:
        _, report = _report()
        mv = report.metrics[metric_id]
        assert mv.value is None, f"{metric_id} published frame units under a metric label"
        assert mv.disabled_reason == "scale_unresolved"


class TestPhaseTiming:
    def test_phase_method_is_the_wrist_heuristic(self) -> None:
        _, report = _report()
        assert report.phase_method == PHASE_METHOD_POSE_WRIST
        assert report.quality.phase_segmentation_method == PHASE_METHOD_POSE_WRIST

    def test_x_factor_is_anchored_at_the_downswing_boundary(self) -> None:
        """BM-04 must be evaluated at downswing start, which must be the turnover."""
        raw, report = _report()
        assert 22 <= raw.phases.downswing <= 30
        assert report.phase_boundaries["downswing"] == raw.phases.downswing

    def test_boundaries_are_ordered(self) -> None:
        _, report = _report()
        b = report.phase_boundaries
        assert b["stance"] <= b["backlift"] <= b["downswing"] <= b["impact"] <= b["follow_through"]


class TestHonestyGates:
    """Rule 3: a capture that cannot support a metric must not report one."""

    def test_bad_angle_disables_the_stride_metric(self) -> None:
        _, report = _report(side_on=False)
        mv = report.metrics[BM_08]
        assert mv.value is None
        assert mv.disabled_reason == "crease_axis_unresolved"

    def test_bad_angle_is_flagged_not_silently_trusted(self) -> None:
        _, report = _report(side_on=False)
        assert "NON_STANDARD_ANGLE" in report.quality.flags

    def test_bad_angle_lowers_confidence_on_the_shipped_metrics(self) -> None:
        _, good = _report(side_on=True)
        _, bad = _report(side_on=False)
        for metric_id in POSE_ONLY_IDS:
            assert bad.metrics[metric_id].confidence < good.metrics[metric_id].confidence

    def test_low_keypoint_confidence_marks_the_run_provisional(self) -> None:
        poor = [
            RawPoseFrame(f.frame_index, {j: (x, y, 0.2) for j, (x, y, _) in f.joints.items()})
            for f in _stroke_pose()
        ]
        raw = build_pose_only_stroke(
            correlation_id="poor",
            pose=poor,
            calibration=_calibration(),
            anthropometrics=Anthropometrics(height_cm=178.0, handedness=RHB),
        )
        report = compute_report(raw)
        assert report.provisional is True
        assert "LOW_CONFIDENCE_INPUT" in report.quality.flags


class TestDeterminism:
    def test_same_input_gives_the_same_report(self) -> None:
        _, a = _report()
        _, b = _report()
        assert a.metrics_payload() == b.metrics_payload()
        assert a.phase_boundaries == b.phase_boundaries
