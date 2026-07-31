"""Plan assembly + dose/timeline tuning to learning speed (M17 Step 5, FR-M17-04, AC-M17-04)."""

from __future__ import annotations

from learning_service.domain.drills import DrillObjective, SelectedDrill
from learning_service.domain.plan import (
    BASE_REPS,
    BASE_SETS,
    BASE_TIMELINE_DAYS,
    REFERENCE_IMPROVEMENT_RATE,
    assemble_plan,
)


def _drill(finding_id: str = "F::A", metric_id: str = "BM-01") -> SelectedDrill:
    return SelectedDrill(
        finding_id=finding_id,
        drill_name="closed-shoulder drill",
        objective=DrillObjective(metric_id=metric_id, comparison="below", threshold=8.0),
        priority_score=18.0,
    )


class TestAssemblePlan:
    def test_plan_carries_the_stage_and_learning_speed(self) -> None:
        plan = assemble_plan([_drill()], stage="associative", learning_speed=0.2)
        assert plan.stage == "associative"
        assert plan.learning_speed == 0.2

    def test_one_item_per_selected_drill(self) -> None:
        plan = assemble_plan(
            [_drill("F::A"), _drill("F::B")], stage="cognitive", learning_speed=None
        )
        assert len(plan.items) == 2

    def test_no_drills_yields_an_empty_plan(self) -> None:
        plan = assemble_plan([], stage="cognitive", learning_speed=None)
        assert plan.items == ()

    def test_each_item_links_to_its_finding_and_objective(self) -> None:
        plan = assemble_plan([_drill()], stage="cognitive", learning_speed=None)
        item = plan.items[0]
        assert item.finding_ref == "F::A"
        assert item.drill_name == "closed-shoulder drill"
        assert item.objective["metric_id"] == "BM-01"
        assert item.target_ref == "F::A:BM-01"

    def test_unknown_learning_speed_uses_the_baseline_dose(self) -> None:
        plan = assemble_plan([_drill()], stage="cognitive", learning_speed=None)
        dose = plan.items[0].dose
        assert dose.reps == BASE_REPS
        assert dose.sets == BASE_SETS
        assert dose.timeline_days == BASE_TIMELINE_DAYS

    def test_stalled_learning_speed_uses_the_baseline_dose(self) -> None:
        plan = assemble_plan([_drill()], stage="cognitive", learning_speed=0.0)
        dose = plan.items[0].dose
        assert dose.reps == BASE_REPS

    def test_faster_learner_gets_a_lighter_dose_than_baseline(self) -> None:
        fast_plan = assemble_plan(
            [_drill()], stage="associative", learning_speed=REFERENCE_IMPROVEMENT_RATE * 2
        )
        assert fast_plan.items[0].dose.reps < BASE_REPS

    def test_slower_learner_gets_a_heavier_dose_than_baseline(self) -> None:
        slow_plan = assemble_plan(
            [_drill()], stage="associative", learning_speed=REFERENCE_IMPROVEMENT_RATE / 2
        )
        assert slow_plan.items[0].dose.reps > BASE_REPS

    def test_reference_learning_speed_matches_the_baseline_dose(self) -> None:
        plan = assemble_plan(
            [_drill()], stage="associative", learning_speed=REFERENCE_IMPROVEMENT_RATE
        )
        assert plan.items[0].dose.reps == BASE_REPS

    def test_dose_multiplier_is_clamped_for_extreme_speeds(self) -> None:
        very_fast = assemble_plan([_drill()], stage="autonomous", learning_speed=100.0)
        very_slow = assemble_plan([_drill()], stage="cognitive", learning_speed=0.0001)
        assert very_fast.items[0].dose.reps >= 1
        assert very_slow.items[0].dose.reps <= BASE_REPS * 2 + 1
