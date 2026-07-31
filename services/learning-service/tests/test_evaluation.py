"""Plan evaluation + adaptation loop (M17 Step 6, FR-M17-05, AC-M17-05)."""

from __future__ import annotations

from learning_service.domain.evaluation import (
    UNMET_TARGET_BOOST,
    adaptation_multiplier,
    evaluate_plan,
)


def _item(
    target_ref: str = "F::A:BM-01", *, comparison: str = "below", threshold: float = 8.0
) -> dict:
    return {
        "target_ref": target_ref,
        "objective": {"metric_id": "BM-01", "comparison": comparison, "threshold": threshold},
    }


def _fact(value: float) -> dict:
    return {"value": value}


class TestEvaluatePlan:
    def test_below_threshold_objective_met_when_current_value_is_low_enough(self) -> None:
        evaluations = evaluate_plan(
            [_item(comparison="below", threshold=8.0)],
            {"BM-01": _fact(6.0)},
            evidence_ref="stroke-2",
        )
        assert evaluations[0].met is True

    def test_below_threshold_objective_unmet_when_current_value_is_too_high(self) -> None:
        evaluations = evaluate_plan(
            [_item(comparison="below", threshold=8.0)],
            {"BM-01": _fact(10.0)},
            evidence_ref="stroke-2",
        )
        assert evaluations[0].met is False

    def test_above_threshold_objective_met_when_current_value_is_high_enough(self) -> None:
        evaluations = evaluate_plan(
            [_item(comparison="above", threshold=4.0)],
            {"BM-01": _fact(5.0)},
            evidence_ref="stroke-2",
        )
        assert evaluations[0].met is True

    def test_no_current_evidence_for_the_metric_is_left_unevaluated(self) -> None:
        evaluations = evaluate_plan([_item()], {}, evidence_ref="stroke-2")
        assert evaluations == []

    def test_item_without_a_target_ref_is_skipped(self) -> None:
        evaluations = evaluate_plan(
            [{"objective": {"metric_id": "BM-01", "comparison": "below", "threshold": 8.0}}],
            {"BM-01": _fact(6.0)},
            evidence_ref="stroke-2",
        )
        assert evaluations == []

    def test_evidence_ref_is_recorded(self) -> None:
        evaluations = evaluate_plan([_item()], {"BM-01": _fact(6.0)}, evidence_ref="report:xyz")
        assert evaluations[0].evidence_ref == "report:xyz"

    def test_no_prior_items_yields_no_evaluations(self) -> None:
        assert evaluate_plan([], {"BM-01": _fact(6.0)}, evidence_ref="stroke-2") == []


class TestAdaptationMultiplier:
    def test_unmet_target_is_boosted(self) -> None:
        evaluations = evaluate_plan(
            [_item(comparison="below", threshold=8.0)],
            {"BM-01": _fact(10.0)},
            evidence_ref="stroke-2",
        )
        assert adaptation_multiplier(evaluations, target_ref="F::A:BM-01") == UNMET_TARGET_BOOST

    def test_met_target_is_not_boosted(self) -> None:
        evaluations = evaluate_plan(
            [_item(comparison="below", threshold=8.0)],
            {"BM-01": _fact(6.0)},
            evidence_ref="stroke-2",
        )
        assert adaptation_multiplier(evaluations, target_ref="F::A:BM-01") == 1.0

    def test_target_ref_never_evaluated_is_not_boosted(self) -> None:
        assert adaptation_multiplier([], target_ref="F::A:BM-01") == 1.0
