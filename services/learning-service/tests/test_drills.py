"""Drill selection with measurable objectives (M17 Step 4, FR-M17-03/07, AC-M17-03/06)."""

from __future__ import annotations

from learning_service.domain.drills import select_drills
from learning_service.domain.prioritization import PrioritizedFault


def _fault(finding_id: str = "F::KG-A:v1", score: float = 18.0) -> PrioritizedFault:
    return PrioritizedFault(
        finding_id=finding_id,
        score=score,
        impact=18.0,
        fixability=1.0,
        readiness=1.0,
        categories=("balance",),
    )


def _finding(
    finding_id: str = "F::KG-A:v1",
    *,
    drill_name: str | None = "closed-shoulder drill",
    metric_id: str | None = "BM-01",
) -> dict:
    finding: dict = {"finding_id": finding_id}
    if drill_name is not None:
        finding["drill"] = {"name": drill_name}
    if metric_id is not None:
        finding["evidence"] = [{"metric_id": metric_id, "value": 12.0}]
    return finding


def _comparison(value: float, low: float, high: float) -> dict:
    return {"value": value, "target_range": [low, high]}


class TestSelectDrills:
    def test_selects_the_grounded_drill_name_from_the_finding(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={"BM-01": _comparison(12.0, 4.0, 8.0)},
        )
        assert len(selected) == 1
        assert selected[0].drill_name == "closed-shoulder drill"

    def test_value_above_range_yields_a_below_threshold_objective(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={"BM-01": _comparison(12.0, 4.0, 8.0)},
        )
        objective = selected[0].objective
        assert objective.comparison == "below"
        assert objective.threshold == 8.0

    def test_value_below_range_yields_an_above_threshold_objective(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={"BM-01": _comparison(2.0, 4.0, 8.0)},
        )
        objective = selected[0].objective
        assert objective.comparison == "above"
        assert objective.threshold == 4.0

    def test_value_within_range_refines_toward_the_midpoint(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={"BM-01": _comparison(7.0, 4.0, 8.0)},
        )
        objective = selected[0].objective
        assert objective.threshold == 6.0
        assert objective.comparison == "below"

    def test_finding_with_no_drill_is_skipped_never_invented(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding(drill_name=None)},
            benchmark_comparisons_by_metric={"BM-01": _comparison(12.0, 4.0, 8.0)},
        )
        assert selected == []

    def test_finding_with_no_metric_evidence_is_skipped(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding(metric_id=None)},
            benchmark_comparisons_by_metric={"BM-01": _comparison(12.0, 4.0, 8.0)},
        )
        assert selected == []

    def test_no_benchmark_comparison_for_the_metric_is_skipped(self) -> None:
        selected = select_drills(
            [_fault()],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={},
        )
        assert selected == []

    def test_finding_not_found_is_skipped(self) -> None:
        selected = select_drills([_fault()], findings_by_id={}, benchmark_comparisons_by_metric={})
        assert selected == []

    def test_priority_score_is_carried_through(self) -> None:
        selected = select_drills(
            [_fault(score=42.0)],
            findings_by_id={"F::KG-A:v1": _finding()},
            benchmark_comparisons_by_metric={"BM-01": _comparison(12.0, 4.0, 8.0)},
        )
        assert selected[0].priority_score == 42.0

    def test_order_follows_the_prioritised_fault_order(self) -> None:
        faults = [_fault("F::A", score=50.0), _fault("F::B", score=10.0)]
        findings = {
            "F::A": _finding("F::A"),
            "F::B": _finding("F::B"),
        }
        comparisons = {"BM-01": _comparison(12.0, 4.0, 8.0)}
        selected = select_drills(
            faults, findings_by_id=findings, benchmark_comparisons_by_metric=comparisons
        )
        assert [s.finding_id for s in selected] == ["F::A", "F::B"]
