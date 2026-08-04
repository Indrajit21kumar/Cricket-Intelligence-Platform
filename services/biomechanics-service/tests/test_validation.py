"""Accuracy gate + snapshot regression (M10 Step 8, AC-M10-06/08, ENG-007).

The gate's job is to BLOCK. These tests prove: the reference compute passes its
own golden set; a change that drifts a metric beyond its class band is blocked;
each tolerance class blocks independently; and the compute is deterministic.
"""

from __future__ import annotations

from dataclasses import replace

from biomechanics_service.domain.builder import RawBatFrame, RawPoseFrame, RawStroke
from biomechanics_service.domain.catalogue import (
    BM_01,
    BM_06,
    BM_12,
    BM_17,
    CLASS_ANGULAR,
    CLASS_LINEAR,
    CLASS_TIMING,
    CLASS_VELOCITY,
)
from biomechanics_service.domain.report import BiomechanicsReport, compute_report
from biomechanics_service.domain.stroke import (
    ANGLE_SIDE_ON,
    Anthropometrics,
    BallContext,
    Calibration,
    Phases,
)
from biomechanics_service.domain.validation import (
    GoldenStroke,
    check_against_snapshot,
    check_determinism,
    run_accuracy_gate,
    snapshot,
)


def _raw(name: str, *, head_drift: float = 0.1) -> RawStroke:
    phases = Phases(
        stance=0, backlift=4, downswing=8, impact=12, follow_through=16, method="standard"
    )
    pose = tuple(
        RawPoseFrame(
            frame_index=i,
            joints={
                "nose": (head_drift * (i / 16), 1.7, 0.9),
                "left_shoulder": (0.2 + 0.01 * i, 1.4, 0.9),
                "right_shoulder": (-0.2, 1.4, 0.9),
                "left_hip": (0.15, 0.9, 0.9),
                "right_hip": (-0.15, 0.9, 0.9),
                "left_knee": (0.3, 0.5, 0.9),
                "left_ankle": (0.3, max(0.1, 0.4 - 0.05 * i), 0.9),
                "right_knee": (-0.1, 0.5, 0.9),
                "right_ankle": (-0.1, 0.1, 0.9),
                "left_wrist": (0.04 * i, 1.0, 0.9),
                "right_wrist": (0.04 * i, 1.0, 0.9),
                "left_elbow": (0.0, 1.2, 0.9),
            },
        )
        for i in range(17)
    )
    bat = tuple(
        RawBatFrame(
            frame_index=i,
            detected=True,
            parts={"handle_bottom": (0.0, 0.8), "blade_tip": (0.5, 0.5), "sweet_spot": (0.35, 0.6)},
        )
        for i in range(17)
    )
    return RawStroke(
        correlation_id=name,
        pose=pose,
        bat=bat,
        phases=phases,
        ball=BallContext(release_frame=2, contact_frame=12, timing_reference="release_relative"),
        anthropometrics=Anthropometrics(height_cm=180.0, handedness="RHB"),
        calibration=Calibration(
            metres_per_unit=1.0,
            fps=60.0,
            camera_angle=ANGLE_SIDE_ON,
            spatial_confidence="high",
            depth_estimated=True,
        ),
        shot_type="cover_drive",
        shot_confidence=0.8,
    )


def _golden() -> list[GoldenStroke]:
    """Truth = the reference compute's own values (a snapshot golden)."""
    strokes = [_raw(f"golden-{i}", head_drift=0.05 * (i + 1)) for i in range(3)]
    golden = []
    for raw in strokes:
        report = compute_report(raw)
        truth = {m: mv.value for m, mv in report.metrics.items() if mv.value is not None}
        golden.append(GoldenStroke(name=raw.correlation_id, raw=raw, truth=truth))
    return golden


class TestAccuracyGate:
    def test_the_reference_compute_passes(self) -> None:
        report = run_accuracy_gate(_golden())
        assert report.passed is True, report.reason
        assert report.scored > 0

    def test_an_angular_drift_beyond_the_band_is_blocked(self) -> None:
        """A change that shifts an angular metric > 5 degrees must not ship.

        Drifts BM-06 (front knee flexion), NOT BM-02. BM-02 is a top-down
        rotation, which monocular capture cannot resolve, so it is disabled
        with ``depth_unresolved`` and scores nothing — drifting a null would
        leave this gate silently proving nothing.
        """

        def drifted(raw: RawStroke) -> BiomechanicsReport:
            report = compute_report(raw)
            metrics = dict(report.metrics)
            mv = metrics[BM_06]
            assert mv.value is not None, "fixture must supply a live angular metric"
            metrics[BM_06] = replace(mv, value=mv.value + 10.0)
            return replace(report, metrics=metrics)

        result = run_accuracy_gate(_golden(), compute_fn=drifted)
        assert result.passed is False
        assert result.reason == CLASS_ANGULAR

    def test_a_linear_drift_beyond_3cm_is_blocked(self) -> None:
        def drifted(raw: RawStroke) -> BiomechanicsReport:
            report = compute_report(raw)
            metrics = dict(report.metrics)
            mv = metrics[BM_01]
            metrics[BM_01] = replace(mv, value=(mv.value or 0.0) + 8.0)
            return replace(report, metrics=metrics)

        result = run_accuracy_gate(_golden(), compute_fn=drifted)
        assert result.passed is False
        assert result.reason == CLASS_LINEAR

    def test_a_velocity_drift_beyond_10pct_is_blocked(self) -> None:
        def drifted(raw: RawStroke) -> BiomechanicsReport:
            report = compute_report(raw)
            metrics = dict(report.metrics)
            mv = metrics[BM_12]
            metrics[BM_12] = replace(mv, value=(mv.value or 1.0) * 1.5)
            return replace(report, metrics=metrics)

        result = run_accuracy_gate(_golden(), compute_fn=drifted)
        assert result.passed is False
        assert result.reason == CLASS_VELOCITY

    def test_a_timing_drift_beyond_2_frames_is_blocked(self) -> None:
        def drifted(raw: RawStroke) -> BiomechanicsReport:
            report = compute_report(raw)
            metrics = dict(report.metrics)
            mv = metrics[BM_17]
            # +100ms at 60fps is 6 frames, well beyond the 2-frame band.
            metrics[BM_17] = replace(mv, value=(mv.value or 0.0) + 100.0)
            return replace(report, metrics=metrics)

        result = run_accuracy_gate(_golden(), compute_fn=drifted)
        assert result.passed is False
        assert result.reason == CLASS_TIMING

    def test_a_small_drift_within_the_band_still_passes(self) -> None:
        """Sub-band error is acceptable, not a regression."""

        def nudged(raw: RawStroke) -> BiomechanicsReport:
            report = compute_report(raw)
            metrics = dict(report.metrics)
            mv = metrics[BM_06]  # a live angular metric, not a disabled one
            assert mv.value is not None
            metrics[BM_06] = replace(mv, value=mv.value + 2.0)  # < 5 deg
            return replace(report, metrics=metrics)

        assert run_accuracy_gate(_golden(), compute_fn=nudged).passed is True

    def test_empty_golden_set_is_not_a_pass(self) -> None:
        report = run_accuracy_gate([])
        assert report.passed is False
        assert report.reason == "empty_golden_set"

    def test_bands_are_reported_per_class(self) -> None:
        report = run_accuracy_gate(_golden())
        assert CLASS_ANGULAR in report.per_class_band
        assert report.per_class_band[CLASS_ANGULAR] == 5.0


class TestDeterminism:
    def test_the_compute_is_deterministic(self) -> None:
        """AC-M10-08 / NFR-M10-03."""
        result = check_determinism([_raw("d1"), _raw("d2", head_drift=0.2)])
        assert result.deterministic is True
        assert result.drifted_metrics == ()

    def test_an_unchanged_snapshot_matches(self) -> None:
        raw = _raw("snap")
        stored = snapshot(raw)
        result = check_against_snapshot(raw, stored)
        assert result.deterministic is True

    def test_a_drifted_snapshot_is_caught(self) -> None:
        raw = _raw("snap")
        stored = snapshot(raw)
        # Tamper with the stored fingerprint -> the recompute no longer matches.
        # Uses a metric that carries a real value, so the mismatch is a genuine
        # numeric drift rather than a null-versus-number comparison.
        assert stored[BM_06] is not None
        stored[BM_06] = stored[BM_06] + 1.0
        result = check_against_snapshot(raw, stored)
        assert result.deterministic is False
        assert BM_06 in result.drifted_metrics
