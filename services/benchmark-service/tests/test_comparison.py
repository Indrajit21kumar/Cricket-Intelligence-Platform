"""Per-metric comparison + gap explanation (M15 Step 3, FR-M15-02/03/07)."""

from __future__ import annotations

from benchmark_service.domain.comparison import (
    NEAR,
    OUTSIDE,
    WITHIN,
    compare_metric,
    compare_metrics,
)


def _fact(value: float, confidence: float = 0.9, provenance: str = "measured") -> dict:
    return {"value": value, "confidence": confidence, "provenance": provenance}


def _dist(low: float, high: float, spread: float = 2.0) -> dict:
    return {"range": [low, high], "spread": spread}


class TestCompareMetric:
    def test_value_inside_range_is_within(self) -> None:
        comparison = compare_metric("BM-01", _fact(6.0), _dist(4.0, 8.0))
        assert comparison is not None
        assert comparison.classification == WITHIN
        assert "within" in comparison.gap.lower()

    def test_value_just_outside_range_within_spread_is_near(self) -> None:
        comparison = compare_metric("BM-01", _fact(9.0), _dist(4.0, 8.0, spread=2.0))
        assert comparison is not None
        assert comparison.classification == NEAR
        assert "just outside" in comparison.gap.lower()

    def test_value_far_outside_range_beyond_spread_is_outside(self) -> None:
        comparison = compare_metric("BM-01", _fact(20.0), _dist(4.0, 8.0, spread=2.0))
        assert comparison is not None
        assert comparison.classification == OUTSIDE
        assert "well outside" in comparison.gap.lower()

    def test_below_range_reports_direction(self) -> None:
        comparison = compare_metric("BM-01", _fact(1.0), _dist(4.0, 8.0, spread=2.0))
        assert comparison is not None
        assert "below" in comparison.gap.lower()

    def test_above_range_reports_direction(self) -> None:
        comparison = compare_metric("BM-01", _fact(20.0), _dist(4.0, 8.0, spread=2.0))
        assert comparison is not None
        assert "above" in comparison.gap.lower()

    def test_gap_is_not_a_bare_delta(self) -> None:
        """FR-M15-03: a coaching gap explanation, not just a number."""
        comparison = compare_metric("BM-01", _fact(20.0), _dist(4.0, 8.0))
        assert comparison is not None
        assert not comparison.gap.strip().replace("-", "").replace(".", "").isdigit()
        assert "BM-01" in comparison.gap

    def test_confidence_and_provenance_propagate_from_the_fact(self) -> None:
        comparison = compare_metric(
            "BM-01", _fact(6.0, confidence=0.72, provenance="estimated"), _dist(4.0, 8.0)
        )
        assert comparison is not None
        assert comparison.confidence == 0.72
        assert comparison.provenance == "estimated"

    def test_no_value_in_fact_yields_no_comparison(self) -> None:
        assert compare_metric("BM-01", {}, _dist(4.0, 8.0)) is None

    def test_no_range_in_distribution_yields_no_comparison(self) -> None:
        assert compare_metric("BM-01", _fact(6.0), {}) is None


class TestCompareMetrics:
    def test_one_comparison_per_metric_present_in_both(self) -> None:
        facts = {"BM-01": _fact(6.0), "BM-02": _fact(10.0)}
        distributions = {"BM-01": _dist(4.0, 8.0)}  # BM-02 has no benchmark distribution
        comparisons = compare_metrics(facts, distributions)
        assert len(comparisons) == 1
        assert comparisons[0].metric_id == "BM-01"

    def test_a_metric_in_the_profile_but_not_measured_is_skipped(self) -> None:
        facts: dict = {}
        distributions = {"BM-01": _dist(4.0, 8.0)}
        assert compare_metrics(facts, distributions) == []

    def test_no_distributions_at_all_compares_nothing(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        assert compare_metrics(facts, {}) == []
