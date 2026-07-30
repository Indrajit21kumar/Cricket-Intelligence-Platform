"""The endorsement guardrail wrapper (M15 Step 6, §11, AC-M15-05)."""

from __future__ import annotations

import inspect

from benchmark_service.domain.comparison import MetricComparison
from benchmark_service.domain.endorsement import (
    DISCLAIMER,
    build_legend_similarity_view,
)
from benchmark_service.domain.legend_similarity import LegendStyleResult


def _gap(metric_id: str = "BM-01") -> MetricComparison:
    return MetricComparison(
        metric_id=metric_id,
        value=6.0,
        classification="within",
        gap=f"{metric_id} (6) is within the benchmark range (4-8).",
        target_range=(4.0, 8.0),
        confidence=0.9,
        provenance="measured",
    )


def _result(label: str = "cover-drive-style-A", similarity: float = 82.0) -> LegendStyleResult:
    return LegendStyleResult(
        style_label=label, similarity=similarity, driving_gaps=(_gap(),), confidence=0.85
    )


class TestBuildLegendSimilarityView:
    def test_no_results_yields_no_view(self) -> None:
        assert build_legend_similarity_view([], benchmark_version="cibl@1") is None

    def test_disclaimer_is_always_present(self) -> None:
        view = build_legend_similarity_view([_result()], benchmark_version="cibl@1")
        assert view is not None
        payload = view.to_dict()
        assert payload["disclaimer"] == DISCLAIMER
        assert "endorse" in DISCLAIMER.lower()
        assert "does not claim" in DISCLAIMER.lower()

    def test_benchmark_version_is_pinned_in_the_view(self) -> None:
        view = build_legend_similarity_view([_result()], benchmark_version="cibl@42")
        assert view is not None
        assert view.to_dict()["benchmark_version"] == "cibl@42"

    def test_every_style_in_the_view_still_carries_its_driving_gaps(self) -> None:
        view = build_legend_similarity_view(
            [_result(), _result(label="B")], benchmark_version="cibl@1"
        )
        assert view is not None
        payload = view.to_dict()
        assert all(len(style["driving_gaps"]) > 0 for style in payload["styles"])

    def test_disclaimer_cannot_be_overridden_by_a_caller(self) -> None:
        """The disclaimer is a fixed module constant, not a parameter — there is
        no argument to build_legend_similarity_view that changes it."""
        signature = inspect.signature(build_legend_similarity_view)
        assert "disclaimer" not in signature.parameters
