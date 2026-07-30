"""Legend Similarity Score (M15 Step 4, FR-M15-04/05, AC-M15-03/04)."""

from __future__ import annotations

from benchmark_service.domain.legend_similarity import (
    LegendStyleResult,
    compute_legend_similarity,
    score_style,
)
from benchmark_service.domain.profiles import LEGEND_STYLE, SKILL_TIER, BenchmarkProfile


def _fact(value: float, confidence: float = 0.9, provenance: str = "measured") -> dict:
    return {"value": value, "confidence": confidence, "provenance": provenance}


def _legend_profile(
    benchmark_id: str = "BN-LEGEND-HIGHBACKLIFT",
    label: str = "Front-foot-dominant, high-backlift style",
    distributions: dict | None = None,
) -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id=benchmark_id,
        type=LEGEND_STYLE,
        scope={"label": label},
        distributions=distributions
        or {
            "BM-01": {"range": [4.0, 8.0], "spread": 2.0},
            "BM-04": {"range": [20.0, 40.0], "spread": 5.0},
        },
        released=True,
    )


class TestScoreStyle:
    def test_perfect_match_scores_100_and_still_has_driving_gaps(self) -> None:
        facts = {"BM-01": _fact(6.0), "BM-04": _fact(30.0)}
        result = score_style(facts, _legend_profile())
        assert result is not None
        assert result.similarity == 100.0
        assert len(result.driving_gaps) == 2  # never a bare percentage — always explained

    def test_partial_mismatch_scores_below_100(self) -> None:
        facts = {"BM-01": _fact(6.0), "BM-04": _fact(60.0)}  # BM-04 far outside
        result = score_style(facts, _legend_profile())
        assert result is not None
        assert result.similarity < 100.0

    def test_driving_gaps_are_sorted_worst_first(self) -> None:
        facts = {"BM-01": _fact(6.0), "BM-04": _fact(60.0)}  # BM-04 is the outlier
        result = score_style(facts, _legend_profile())
        assert result is not None
        assert result.driving_gaps[0].metric_id == "BM-04"

    def test_style_label_comes_from_scope(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        result = score_style(facts, _legend_profile(label="Classical side-on orthodox"))
        assert result is not None
        assert result.style_label == "Classical side-on orthodox"

    def test_falls_back_to_benchmark_id_when_no_label(self) -> None:
        profile = BenchmarkProfile(
            benchmark_id="BN-LEGEND-X",
            type=LEGEND_STYLE,
            scope={},
            distributions={"BM-01": {"range": [4.0, 8.0], "spread": 2.0}},
            released=True,
        )
        result = score_style({"BM-01": _fact(6.0)}, profile)
        assert result is not None
        assert result.style_label == "BN-LEGEND-X"

    def test_no_comparable_metrics_yields_no_score(self) -> None:
        facts = {"BM-99": _fact(6.0)}  # nothing overlaps the profile's distributions
        assert score_style(facts, _legend_profile()) is None

    def test_confidence_is_the_mean_of_compared_facts(self) -> None:
        facts = {"BM-01": _fact(6.0, confidence=0.8), "BM-04": _fact(30.0, confidence=0.6)}
        result = score_style(facts, _legend_profile())
        assert result is not None
        assert result.confidence == 0.7


class TestComputeLegendSimilarity:
    def test_ranks_styles_best_first(self) -> None:
        good = _legend_profile(benchmark_id="BN-GOOD", label="good-style")
        bad = _legend_profile(
            benchmark_id="BN-BAD",
            label="bad-style",
            distributions={"BM-01": {"range": [20.0, 24.0], "spread": 2.0}},
        )
        facts = {"BM-01": _fact(6.0), "BM-04": _fact(30.0)}
        results = compute_legend_similarity(facts, [bad, good])
        assert [r.style_label for r in results] == ["good-style", "bad-style"]

    def test_non_legend_profiles_are_ignored(self) -> None:
        tier_profile = BenchmarkProfile(
            benchmark_id="BN-TIER", type=SKILL_TIER, distributions={"BM-01": {"range": [4.0, 8.0]}}
        )
        results = compute_legend_similarity({"BM-01": _fact(6.0)}, [tier_profile])
        assert results == []

    def test_uncomparable_styles_are_omitted_not_zero_scored(self) -> None:
        results = compute_legend_similarity({"BM-99": _fact(1.0)}, [_legend_profile()])
        assert results == []

    def test_every_result_carries_driving_gaps_never_a_bare_percentage(self) -> None:
        """FR-M15-05 / AC-M15-04, at the aggregate level."""
        facts = {"BM-01": _fact(6.0), "BM-04": _fact(30.0)}
        results = compute_legend_similarity(facts, [_legend_profile()])
        assert all(isinstance(r, LegendStyleResult) and len(r.driving_gaps) > 0 for r in results)
