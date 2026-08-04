"""M14 shows the pose-first metrics honestly (Pose-First MVP, Step 4).

A coach reads the report, so it must show only numbers that exist, name the
unit for each, and explain the absence of everything else. These tests feed
M14 the exact payload shape M10 publishes for a pose-only stroke — five real
body metrics, no bat/ball/shot — and check what comes out the other side.
"""

from __future__ import annotations

from typing import Any

import pytest

from report_service.domain.report import build_report

#: The M10 payload for a pose-only stroke, in the shape service.py publishes.
POSE_ONLY_BIOMECHANICS: dict[str, Any] = {
    "phase_boundaries": {
        "stance": 0,
        "backlift": 193,
        "downswing": 256,
        "impact": 284,
        "follow_through": 285,
    },
    "phase_method": "pose_wrist_heuristic",
    "metrics": {
        "BM-05": {
            "value": 43.24,
            "name": "pelvic_tilt",
            "unit": "deg",
            "provenance": "measured",
            "confidence": 0.4,
        },
        "BM-06": {
            "value": 135.61,
            "name": "front_knee_flexion",
            "unit": "deg",
            "provenance": "measured",
            "confidence": 0.4,
        },
        "BM-14": {
            "value": 66.67,
            "name": "balance_recovery",
            "unit": "ms",
            "provenance": "measured",
            "confidence": 0.4,
        },
        "BM-15": {
            "value": 0.52,
            "name": "weight_transfer",
            "unit": "ratio",
            "provenance": "estimated",
            "confidence": 0.28,
        },
        "BM-17": {
            "value": 0.0,
            "name": "ground_contact_timing",
            "unit": "ms",
            "provenance": "measured",
            "confidence": 0.4,
        },
        # Withheld, each for its own reason.
        "BM-04": {
            "value": None,
            "name": "x_factor",
            "unit": "deg",
            "provenance": "measured",
            "confidence": 0.0,
            "disabled_reason": "depth_unresolved",
        },
        "BM-01": {
            "value": None,
            "name": "head_stability",
            "unit": "cm",
            "provenance": "measured",
            "confidence": 0.0,
            "disabled_reason": "scale_unresolved",
        },
        "BM-08": {
            "value": None,
            "name": "stride_length",
            "unit": "pct_height",
            "provenance": "measured",
            "confidence": 0.0,
            "disabled_reason": "crease_axis_unresolved",
        },
        "BM-09": {
            "value": None,
            "name": "backlift",
            "unit": "deg",
            "provenance": "measured",
            "confidence": 0.0,
        },
    },
    "quality": {"fps": 30.0, "phase_segmentation_method": "pose_wrist_heuristic"},
    "provisional": False,
}

REASONED: dict[str, Any] = {
    "correlation_id": "pose-first-1",
    "person_id": "p1",
    # No classifier ran, so no stroke is named.
    "shot_type": None,
    "shot_confidence": None,
    "kg_version": "kg-1",
    "findings": [],
    "match_risk": {},
    "provisional": False,
}


@pytest.fixture
def report():  # type: ignore[no-untyped-def]
    return build_report(reasoned=REASONED, biomechanics=POSE_ONLY_BIOMECHANICS)


class TestDeliveredMetrics:
    def test_only_metrics_with_values_are_delivered(self, report) -> None:  # type: ignore[no-untyped-def]
        assert {p.metric_id for p in report.delivered_panels} == {
            "BM-05",
            "BM-06",
            "BM-14",
            "BM-15",
            "BM-17",
        }

    def test_every_delivered_metric_has_value_unit_and_confidence(self, report) -> None:  # type: ignore[no-untyped-def]
        """Step 4: value, unit and confidence for each shown metric."""
        for panel in report.delivered_panels:
            assert panel.value is not None
            assert panel.unit, f"{panel.metric_id} has no unit to render"
            assert panel.confidence is not None
            assert panel.name, f"{panel.metric_id} has no readable name"

    def test_no_delivered_metric_is_bat_or_ball_derived(self, report) -> None:  # type: ignore[no-untyped-def]
        bat_ball = {"BM-09", "BM-10", "BM-11", "BM-12", "BM-13"}
        assert not (bat_ball & {p.metric_id for p in report.delivered_panels})

    def test_estimated_provenance_survives_to_the_reader(self, report) -> None:  # type: ignore[no-untyped-def]
        """A proxy must stay visibly distinct from a measurement."""
        weight_transfer = next(p for p in report.delivered_panels if p.metric_id == "BM-15")
        assert weight_transfer.provenance == "estimated"


class TestWithheldMetricsAreExplained:
    def test_withheld_metrics_carry_no_value(self, report) -> None:  # type: ignore[no-untyped-def]
        assert all(p.value is None for p in report.withheld_panels)

    def test_every_withheld_metric_has_a_plain_english_reason(self, report) -> None:  # type: ignore[no-untyped-def]
        for panel in report.withheld_panels:
            assert panel.withheld_explanation, f"{panel.metric_id} vanished without explanation"

    def test_x_factor_explains_it_needs_a_second_camera(self, report) -> None:  # type: ignore[no-untyped-def]
        x_factor = next(p for p in report.withheld_panels if p.metric_id == "BM-04")
        assert "two camera angles" in (x_factor.withheld_explanation or "")

    def test_scale_metric_explains_the_missing_calibration(self, report) -> None:  # type: ignore[no-untyped-def]
        head = next(p for p in report.withheld_panels if p.metric_id == "BM-01")
        assert "scale" in (head.withheld_explanation or "").lower()

    def test_bat_metric_explains_bat_tracking_is_unavailable(self, report) -> None:  # type: ignore[no-untyped-def]
        backlift = next(p for p in report.withheld_panels if p.metric_id == "BM-09")
        assert "bat tracking" in (backlift.withheld_explanation or "")

    def test_an_unmapped_reason_falls_back_to_the_slug(self) -> None:
        """A new M10 reason must surface, not disappear."""
        payload = {
            "metrics": {
                "BM-05": {
                    "value": None,
                    "unit": "deg",
                    "provenance": "measured",
                    "confidence": 0.0,
                    "disabled_reason": "some_future_reason",
                }
            }
        }
        r = build_report(reasoned=REASONED, biomechanics=payload)
        assert r.withheld_panels[0].withheld_explanation == "some_future_reason"


class TestPhaseTiming:
    def test_phase_boundaries_are_carried(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report.phase_timing["boundaries"]["downswing"] == 256
        assert report.phase_timing["boundaries"]["impact"] == 284

    def test_the_timing_method_is_disclosed(self, report) -> None:  # type: ignore[no-untyped-def]
        """The reader must know the timing came from body motion, not a ball."""
        assert report.phase_timing["method"] == "pose_wrist_heuristic"

    def test_fps_is_carried_so_frames_can_be_read_as_time(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report.phase_timing["fps"] == 30.0

    def test_absent_phase_data_yields_an_empty_block_not_a_guess(self) -> None:
        r = build_report(reasoned=REASONED, biomechanics={"metrics": {}})
        assert r.phase_timing == {}


class TestNoFakeSectionsAppear:
    def test_no_shot_type_is_claimed(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report.shot_type is None
        assert report.shot_confidence is None

    def test_legend_section_is_omitted_without_m15(self, report) -> None:  # type: ignore[no-untyped-def]
        assert report.legend_view is None

    def test_serialised_report_separates_shown_from_explained(self, report) -> None:  # type: ignore[no-untyped-def]
        payload = report.to_dict()
        assert len(payload["delivered_metrics"]) == 5
        assert len(payload["withheld_metrics"]) == 4
        assert payload["phase_timing"]["method"] == "pose_wrist_heuristic"

    def test_serialised_delivered_metrics_all_carry_numbers(self, report) -> None:  # type: ignore[no-untyped-def]
        for entry in report.to_dict()["delivered_metrics"]:
            assert entry["value"] is not None
            assert entry["unit"]
