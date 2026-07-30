"""The Scoring Standard (M14 Step 2, Book 4 Ch. 8)."""

from __future__ import annotations

from typing import Any

from report_service.domain.scoring import compute_improvement, compute_scores
from report_service.domain.sources import PlayerHistory


def _finding(
    metric_ids: list[str], confidence: float, finding_id: str = "F::KG-A:v1"
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "confidence": confidence,
        "evidence": [
            {"metric_id": m, "value": 1.0, "confidence": 0.9, "provenance": "measured"}
            for m in metric_ids
        ],
    }


class TestCategoryScores:
    def test_a_clean_stroke_scores_100_in_every_category(self) -> None:
        scores = compute_scores([], {})
        assert scores.technique.value == 100.0
        assert scores.timing.value == 100.0
        assert scores.power.value == 100.0
        assert scores.balance.value == 100.0
        assert scores.footwork.value == 100.0

    def test_a_finding_deducts_from_its_evidenced_categories(self) -> None:
        # BM-01 -> balance only.
        scores = compute_scores([_finding(["BM-01"], 1.0)], {})
        assert scores.balance.value == 80.0  # 100 - 20*1.0
        assert scores.technique.value == 100.0  # untouched

    def test_confidence_scales_the_penalty(self) -> None:
        scores = compute_scores([_finding(["BM-01"], 0.5)], {})
        assert scores.balance.value == 90.0  # 100 - 20*0.5

    def test_bm17_penalises_both_timing_and_footwork(self) -> None:
        """Ch. 8 names ground-contact timing under both categories."""
        scores = compute_scores([_finding(["BM-17"], 1.0)], {})
        assert scores.timing.value == 80.0
        assert scores.footwork.value == 80.0

    def test_score_never_goes_below_zero(self) -> None:
        findings = [_finding(["BM-01"], 1.0, finding_id=f"F::{i}") for i in range(10)]
        scores = compute_scores(findings, {})
        assert scores.balance.value == 0.0

    def test_category_reports_its_inputs(self) -> None:
        scores = compute_scores([_finding(["BM-01"], 1.0)], {})
        assert scores.balance.inputs == ("BM-01",)


class TestOverall:
    def test_overall_is_the_mean_of_the_five_categories(self) -> None:
        scores = compute_scores([_finding(["BM-01"], 1.0)], {})  # balance -> 80, rest 100
        assert scores.overall.value == round((80 + 100 * 4) / 5, 1)

    def test_confidence_and_improvement_are_not_folded_into_overall(self) -> None:
        scores = compute_scores(
            [], {"BM-01": {"value": 1, "confidence": 0.2, "provenance": "measured"}}
        )
        # Low input confidence must not drag Overall down — it's reported separately.
        assert scores.overall.value == 100.0
        assert scores.confidence.value is not None and scores.confidence.value < 100.0


class TestConfidenceScore:
    def test_uses_finding_confidence_when_findings_exist(self) -> None:
        scores = compute_scores([_finding(["BM-01"], 0.6), _finding(["BM-02"], 0.8, "F::B")], {})
        assert scores.confidence.value == 70.0  # mean(0.6, 0.8) * 100

    def test_falls_back_to_fact_confidence_when_no_findings(self) -> None:
        facts = {
            "BM-01": {"value": 1, "confidence": 0.9, "provenance": "measured"},
            "BM-02": {"value": 1, "confidence": 0.7, "provenance": "measured"},
        }
        scores = compute_scores([], facts)
        assert scores.confidence.value == 80.0

    def test_no_findings_no_facts_is_honestly_unavailable(self) -> None:
        scores = compute_scores([], {})
        assert scores.confidence.value is None
        assert scores.confidence.unavailable_reason == "no_facts"


class TestImprovement:
    def test_no_history_is_honestly_unavailable(self) -> None:
        entry = compute_improvement([], [])
        assert entry.value is None and entry.unavailable_reason == "no_history"

    def test_improvement_on_a_lower_is_better_metric(self) -> None:
        # BM-01 head stability: lower is better. Improved from 10cm to 8cm (-20%).
        panels = [{"metric_id": "BM-01", "value": 8.0, "confidence": 0.9}]
        history = [PlayerHistory(metric_key="BM-01", baseline_value=10.0, baseline_confidence=0.9)]
        entry = compute_improvement(panels, history)
        assert entry.value is not None and entry.value > 50.0  # improved

    def test_regression_scores_below_50(self) -> None:
        # Head stability got WORSE (10cm -> 13cm).
        panels = [{"metric_id": "BM-01", "value": 13.0, "confidence": 0.9}]
        history = [PlayerHistory(metric_key="BM-01", baseline_value=10.0, baseline_confidence=0.9)]
        entry = compute_improvement(panels, history)
        assert entry.value is not None and entry.value < 50.0

    def test_a_metric_without_a_documented_direction_is_excluded(self) -> None:
        panels = [
            {"metric_id": "BM-05", "value": 5.0, "confidence": 0.9}
        ]  # not in HIGHER_IS_BETTER
        history = [PlayerHistory(metric_key="BM-05", baseline_value=4.0, baseline_confidence=0.9)]
        entry = compute_improvement(panels, history)
        assert entry.value is None and entry.unavailable_reason == "no_matching_baseline"
