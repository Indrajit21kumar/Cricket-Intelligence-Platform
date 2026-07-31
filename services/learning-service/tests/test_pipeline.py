"""Training-plan pipeline — pure orchestration (M17 Step 7)."""

from __future__ import annotations

from learning_service.domain.pipeline import compute_plan


def _finding(
    finding_id: str = "F::A", *, metric_id: str = "BM-01", confidence: float = 0.9
) -> dict:
    return {
        "finding_id": finding_id,
        "confidence": confidence,
        "provenance": "measured",
        "evidence": [{"metric_id": metric_id, "value": 1.0}],
        "drill": {"name": "closed-shoulder drill"},
    }


def _comparison(value: float = 12.0, low: float = 4.0, high: float = 8.0) -> dict:
    return {"value": value, "target_range": [low, high]}


class TestComputePlan:
    def test_no_signals_defaults_to_cognitive_stage(self) -> None:
        result = compute_plan(
            findings=[_finding()],
            benchmark_comparisons_by_metric={"BM-01": _comparison()},
            consistency_deviations=[],
            trait_deltas=[],
        )
        assert result.stage == "cognitive"

    def test_grounded_finding_with_comparison_yields_a_plan_item(self) -> None:
        result = compute_plan(
            findings=[_finding()],
            benchmark_comparisons_by_metric={"BM-01": _comparison()},
            consistency_deviations=[0.1, 0.1],
            trait_deltas=[0.01, 0.01],
        )
        assert len(result.items) == 1
        assert result.items[0]["drill_name"] == "closed-shoulder drill"

    def test_no_findings_yields_an_empty_plan(self) -> None:
        result = compute_plan(
            findings=[],
            benchmark_comparisons_by_metric={},
            consistency_deviations=[],
            trait_deltas=[],
        )
        assert result.items == []

    def test_consistency_and_learning_speed_are_reported(self) -> None:
        result = compute_plan(
            findings=[_finding()],
            benchmark_comparisons_by_metric={"BM-01": _comparison()},
            consistency_deviations=[0.2, 0.4],
            trait_deltas=[0.05, 0.1],
        )
        assert result.consistency is not None
        assert result.learning_speed is not None

    def test_adaptation_boosts_the_matching_items_dose(self) -> None:
        plain = compute_plan(
            findings=[_finding()],
            benchmark_comparisons_by_metric={"BM-01": _comparison()},
            consistency_deviations=[],
            trait_deltas=[],
        )
        adapted = compute_plan(
            findings=[_finding()],
            benchmark_comparisons_by_metric={"BM-01": _comparison()},
            consistency_deviations=[],
            trait_deltas=[],
            adaptation_by_target_ref={"F::A:BM-01": 1.5},
        )
        assert adapted.items[0]["dose"]["reps"] > plain.items[0]["dose"]["reps"]

    def test_result_is_reproducible_given_the_same_inputs(self) -> None:
        kwargs = {
            "findings": [_finding()],
            "benchmark_comparisons_by_metric": {"BM-01": _comparison()},
            "consistency_deviations": [0.1, 0.2],
            "trait_deltas": [0.05],
        }
        a = compute_plan(**kwargs).to_dict()
        b = compute_plan(**kwargs).to_dict()
        assert a == b
