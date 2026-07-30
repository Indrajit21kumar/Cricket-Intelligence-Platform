"""Legend comparison view + the endorsement guardrail (M14 Step 4, FR-M14-05)."""

from __future__ import annotations

from typing import Any

import pytest

from report_service.domain.legend import (
    DISCLAIMER,
    EndorsementGuardrailError,
    LegendStyleComparison,
    build_legend_view,
)


def _gap(metric_id: str = "BM-01") -> dict[str, Any]:
    return {
        "metric_id": metric_id,
        "description": "backlift starts later than the benchmark",
        "player_value": 12.0,
        "benchmark_value": 8.0,
    }


def _comparison(styles: list[dict[str, Any]], benchmark_version: str = "cibl@1") -> dict[str, Any]:
    return {"styles": styles, "benchmark_version": benchmark_version}


def _style(similarity: float = 72.0, gaps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "style_label": "cover-drive-style-A",
        "similarity": similarity,
        "driving_gaps": gaps if gaps is not None else [_gap()],
        "confidence": 0.8,
    }


class TestBuildLegendView:
    def test_no_comparison_yet_is_honestly_absent(self) -> None:
        assert build_legend_view(None) is None

    def test_renders_a_style_with_its_driving_gaps(self) -> None:
        view = build_legend_view(_comparison([_style()]))
        assert view is not None
        assert len(view.styles) == 1
        assert view.styles[0].similarity == 72.0
        assert view.styles[0].driving_gaps[0].metric_id == "BM-01"
        assert view.benchmark_version == "cibl@1"

    def test_disclaimer_always_present_in_output(self) -> None:
        view = build_legend_view(_comparison([_style()]))
        assert view is not None
        payload = view.to_dict()
        assert payload["disclaimer"] == DISCLAIMER
        assert "endorse" in DISCLAIMER.lower()

    def test_a_style_with_no_driving_gaps_is_dropped_not_rendered_bare(self) -> None:
        """FR-M15-05 / AC-M14-05: never emit a similarity figure without gaps."""
        view = build_legend_view(_comparison([_style(gaps=[])]))
        assert view is None

    def test_a_bare_style_is_dropped_while_a_valid_sibling_still_renders(self) -> None:
        view = build_legend_view(_comparison([_style(gaps=[]), _style(similarity=55.0)]))
        assert view is not None
        assert len(view.styles) == 1
        assert view.styles[0].similarity == 55.0

    def test_malformed_styles_field_yields_no_legend_section(self) -> None:
        assert build_legend_view({"styles": "not-a-list"}) is None

    def test_no_styles_at_all_yields_no_legend_section(self) -> None:
        assert build_legend_view(_comparison([])) is None


class TestEndorsementGuardrailStructural:
    def test_constructing_a_style_without_gaps_raises(self) -> None:
        with pytest.raises(EndorsementGuardrailError):
            LegendStyleComparison(
                style_label="cover-drive-style-A",
                similarity=90.0,
                driving_gaps=(),
                confidence=0.9,
            )
