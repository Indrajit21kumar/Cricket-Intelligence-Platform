"""Metric panels — provenance + confidence passthrough (M14 Step 2, AC-M14-02)."""

from __future__ import annotations

from typing import Any

from report_service.domain.panels import build_metric_panels


def _bio() -> dict[str, Any]:
    return {
        "metrics": {
            "BM-01": {"value": 5.0, "provenance": "measured", "confidence": 0.9},
            "BM-07": {
                "value": None,
                "provenance": "measured",
                "confidence": 0.0,
                "disabled_reason": "crease_axis_unresolved",
            },
        }
    }


def _phys() -> dict[str, Any]:
    return {"quantities": {"PH-06": {"value": 42.0, "provenance": "estimated", "confidence": 0.6}}}


class TestBuildMetricPanels:
    def test_carries_provenance_and_confidence(self) -> None:
        panels = build_metric_panels(biomechanics=_bio(), physics=_phys())
        by_id = {p.metric_id: p for p in panels}
        assert by_id["BM-01"].provenance == "measured"
        assert by_id["PH-06"].provenance == "estimated"
        assert by_id["PH-06"].confidence == 0.6

    def test_a_disabled_metric_is_included_with_no_value(self) -> None:
        panels = build_metric_panels(biomechanics=_bio())
        by_id = {p.metric_id: p for p in panels}
        assert by_id["BM-07"].value is None
        assert by_id["BM-07"].disabled_reason == "crease_axis_unresolved"

    def test_estimated_is_visibly_distinct_from_measured(self) -> None:
        panels = build_metric_panels(biomechanics=_bio(), physics=_phys())
        provenances = {p.metric_id: p.provenance for p in panels}
        assert provenances["BM-01"] != provenances["PH-06"]

    def test_no_physics_still_builds(self) -> None:
        panels = build_metric_panels(biomechanics=_bio())
        assert {p.metric_id for p in panels} == {"BM-01", "BM-07"}
