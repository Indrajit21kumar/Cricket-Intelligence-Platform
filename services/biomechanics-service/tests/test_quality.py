"""Confidence + precondition + degradation (M10 Step 5, AC-M10-03)."""

from __future__ import annotations

from biomechanics_service.domain.catalogue import (
    BM_01,
    BM_07,
    BM_08,
    BM_09,
    BM_15,
    FLAG_ABSOLUTE_TIMING,
    FLAG_BAT_LOSS,
    FLAG_LOW_CONFIDENCE_INPUT,
    FLAG_NON_STANDARD_ANGLE,
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
)
from biomechanics_service.domain.phase_align import align_phases
from biomechanics_service.domain.quality import (
    assess_quality,
    finalise_metrics,
)
from biomechanics_service.domain.stroke import (
    ANGLE_SIDE_ON,
    SPATIAL_HIGH,
    SPATIAL_LOW,
    Anthropometrics,
    BallContext,
    Calibration,
    NormalisedStroke,
    Phases,
    PoseFrame,
)

PHASES = Phases(stance=0, backlift=4, downswing=8, impact=12, follow_through=16, method="standard")
BALL = BallContext(release_frame=2, contact_frame=15, timing_reference="release_relative")
ANTHRO = Anthropometrics(height_cm=180.0, handedness="RHB")


def _cal(
    *, angle: str = ANGLE_SIDE_ON, spatial: str = SPATIAL_HIGH, depth: bool = True
) -> Calibration:
    return Calibration(
        metres_per_unit=1.0,
        fps=60.0,
        camera_angle=angle,
        spatial_confidence=spatial,
        depth_estimated=depth,
    )


def _stroke(
    *,
    frame_confidences: list[float],
    cal: Calibration | None = None,
    bat_loss: float | None = None,
    timing: str = "release_relative",
) -> NormalisedStroke:
    pose = tuple(
        PoseFrame(frame_index=i, joints={}, mean_confidence=c)
        for i, c in enumerate(frame_confidences)
    )
    return NormalisedStroke(
        correlation_id="c",
        pose_frames=pose,
        bat_frames=(),
        phases=PHASES,
        ball=BallContext(release_frame=2, contact_frame=15, timing_reference=timing),
        anthropometrics=ANTHRO,
        calibration=cal or _cal(),
        bat_downswing_failure_ratio=bat_loss,
    )


def _aligned(frame_count: int):  # type: ignore[no-untyped-def]
    return align_phases(PHASES, frame_count=frame_count)


class TestPrecondition:
    def test_good_pose_is_not_provisional(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        assert quality.provisional is False
        assert FLAG_LOW_CONFIDENCE_INPUT not in quality.flags

    def test_below_80_percent_good_frames_is_provisional(self) -> None:
        """AC-M10-03: REQ-BIO-003 precondition."""
        # 15 of 20 frames good = 75% < 80%.
        confs = [0.9] * 15 + [0.3] * 5
        stroke = _stroke(frame_confidences=confs)
        quality = assess_quality(stroke, _aligned(20))
        assert quality.provisional is True
        assert FLAG_LOW_CONFIDENCE_INPUT in quality.flags

    def test_exactly_80_percent_is_not_provisional(self) -> None:
        # 16 of 20 = exactly 80%, which clears the floor.
        confs = [0.9] * 16 + [0.3] * 4
        stroke = _stroke(frame_confidences=confs)
        quality = assess_quality(stroke, _aligned(20))
        assert quality.provisional is False


class TestBatLoss:
    def test_over_30_percent_bat_loss_flags_but_does_not_sink_the_report(self) -> None:
        """FR-M10-06: bat loss degrades the bat metrics, not the whole report."""
        stroke = _stroke(frame_confidences=[0.9] * 20, bat_loss=0.35)
        quality = assess_quality(stroke, _aligned(20))
        assert FLAG_BAT_LOSS in quality.flags
        # The body metrics are still sound, so the report is not provisional.
        assert quality.provisional is False

    def test_exactly_30_percent_bat_loss_is_not_flagged(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20, bat_loss=0.30)
        quality = assess_quality(stroke, _aligned(20))
        assert FLAG_BAT_LOSS not in quality.flags

    def test_bat_loss_marks_only_bat_dependent_metrics_provisional(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20, bat_loss=0.5)
        quality = assess_quality(stroke, _aligned(20))
        raw = {BM_01: 5.0, BM_09: 60.0}
        finalised = finalise_metrics(stroke, raw, quality)
        # BM-09 is bat-dependent; BM-01 is not.
        assert finalised[BM_09].provisional is True
        assert finalised[BM_01].provisional is False
        assert finalised[BM_09].confidence < finalised[BM_01].confidence


class TestCameraAngle:
    def test_non_side_on_disables_x_axis_metrics(self) -> None:
        """§14: BM-07/BM-08 disabled, not reported wrong."""
        stroke = _stroke(frame_confidences=[0.9] * 20, cal=_cal(angle="front_on"))
        quality = assess_quality(stroke, _aligned(20))
        assert FLAG_NON_STANDARD_ANGLE in quality.flags
        finalised = finalise_metrics(stroke, {BM_07: 30.0, BM_08: 50.0}, quality)
        assert finalised[BM_07].value is None
        assert finalised[BM_07].disabled_reason == "crease_axis_unresolved"
        assert finalised[BM_08].value is None

    def test_low_spatial_confidence_also_disables_them(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20, cal=_cal(spatial=SPATIAL_LOW))
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_07: 30.0}, quality)
        assert finalised[BM_07].value is None

    def test_side_on_keeps_x_axis_metrics(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_07: 30.0, BM_08: 50.0}, quality)
        assert finalised[BM_07].value == 30.0


class TestProvenance:
    def test_bm15_is_estimated_others_measured(self) -> None:
        """FR-M10-07: BM-15 is the labelled estimated proxy."""
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_01: 5.0, BM_15: 0.6}, quality)
        assert finalised[BM_15].provenance == PROVENANCE_ESTIMATED
        assert finalised[BM_01].provenance == PROVENANCE_MEASURED

    def test_estimated_proxy_has_lower_confidence(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_01: 5.0, BM_15: 0.6}, quality)
        assert finalised[BM_15].confidence < finalised[BM_01].confidence

    def test_a_missing_value_has_zero_confidence(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_01: None}, quality)
        assert finalised[BM_01].confidence == 0.0


class TestConfidenceBands:
    def test_high_spatial_beats_low_spatial(self) -> None:
        high = _stroke(frame_confidences=[0.9] * 20, cal=_cal(spatial=SPATIAL_HIGH))
        low = _stroke(frame_confidences=[0.9] * 20, cal=_cal(spatial=SPATIAL_HIGH, depth=False))
        qh = assess_quality(high, _aligned(20))
        ql = assess_quality(low, _aligned(20))
        fh = finalise_metrics(high, {BM_01: 5.0}, qh)
        fl = finalise_metrics(low, {BM_01: 5.0}, ql)
        # depth_estimated softens the linear metric's confidence.
        assert fh[BM_01].confidence < fl[BM_01].confidence

    def test_provisional_caps_confidence(self) -> None:
        stroke = _stroke(frame_confidences=[0.3] * 20)  # fails precondition
        quality = assess_quality(stroke, _aligned(20))
        finalised = finalise_metrics(stroke, {BM_01: 5.0}, quality)
        assert finalised[BM_01].confidence <= 0.5


class TestAbsoluteTiming:
    def test_absolute_timing_is_flagged(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20, timing="absolute")
        quality = assess_quality(stroke, _aligned(20))
        assert FLAG_ABSOLUTE_TIMING in quality.flags

    def test_method_is_propagated(self) -> None:
        stroke = _stroke(frame_confidences=[0.9] * 20)
        quality = assess_quality(stroke, _aligned(20))
        assert quality.phase_segmentation_method == "standard"
