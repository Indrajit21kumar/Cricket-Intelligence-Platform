"""Training-plan pipeline — pure orchestration (M17 Step 7).

Ties Steps 2-6 together: infer the learning stage from consistency +
improvement-rate signals, prioritise current M13 findings by
impact x fixability x stage-readiness, select grounded drills with
measurable objectives from M15's benchmark comparisons, and assemble the
plan — doses adapted from the prior cycle's evaluation (Step 6) on top of
the learning-speed tuning (Step 5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from learning_service.domain.drills import select_drills
from learning_service.domain.plan import assemble_plan
from learning_service.domain.prioritization import prioritize_faults
from learning_service.domain.stage import (
    LearningSignals,
    compute_consistency,
    compute_improvement_rate,
    infer_stage,
)

SCHEMA_VERSION = "plan.updated/1.0"


@dataclass(frozen=True, slots=True)
class PlanResult:
    stage: str
    items: list[dict[str, Any]]
    learning_speed: float | None
    consistency: float | None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "items": self.items,
            "learning_speed": self.learning_speed,
            "consistency": self.consistency,
            "schema_version": self.schema_version,
        }


def compute_plan(
    *,
    findings: Sequence[Mapping[str, Any]],
    benchmark_comparisons_by_metric: Mapping[str, Mapping[str, Any]],
    consistency_deviations: Sequence[float],
    trait_deltas: Sequence[float],
    adaptation_by_target_ref: Mapping[str, float] | None = None,
) -> PlanResult:
    """Assemble one player's training plan from this cycle's evidence."""
    consistency = compute_consistency(consistency_deviations)
    improvement_rate = compute_improvement_rate(trait_deltas)
    stage_estimate = infer_stage(
        LearningSignals(consistency=consistency, improvement_rate=improvement_rate)
    )

    prioritized = prioritize_faults(findings, stage=stage_estimate.stage)
    findings_by_id = {
        finding["finding_id"]: finding
        for finding in findings
        if isinstance(finding.get("finding_id"), str)
    }
    selected = select_drills(
        prioritized,
        findings_by_id=findings_by_id,
        benchmark_comparisons_by_metric=benchmark_comparisons_by_metric,
    )

    plan = assemble_plan(
        selected,
        stage=stage_estimate.stage,
        learning_speed=improvement_rate,
        adaptation_by_target_ref=adaptation_by_target_ref,
    )

    return PlanResult(
        stage=plan.stage,
        items=[item.to_dict() for item in plan.items],
        learning_speed=plan.learning_speed,
        consistency=consistency,
    )
