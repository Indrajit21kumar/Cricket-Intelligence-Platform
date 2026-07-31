"""Plan evaluation + adaptation loop (M17 Step 6, FR-M17-05, AC-M17-05).

Checks whether each prior plan item's measurable objective (Step 4/5) was
met by the CURRENT session's evidence for that item's metric. An item with
no current evidence for its metric is honestly left unevaluated (skipped),
never assumed met or unmet.

An unmet target's next dose gets boosted (:data:`UNMET_TARGET_BOOST`) rather
than repeated unchanged — the same dose clearly wasn't enough. A met target
needs no boost; its underlying finding usually won't even recur in the next
session's prioritisation (M13 only reports faults still actionable).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

ADAPTATION_MODEL_VERSION = "plan-adaptation-1.0.0"

#: How much an unmet target's next dose multiplier is boosted — an explicit,
#: versioned choice (the spec says "adjust dose", not by how much).
UNMET_TARGET_BOOST = 1.5


@dataclass(frozen=True, slots=True)
class PlanEvaluation:
    """Whether one prior plan item's target was met (persisted to plan_evaluations)."""

    target_ref: str
    met: bool
    evidence_ref: str | None
    model_version: str = ADAPTATION_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_ref": self.target_ref,
            "met": self.met,
            "evidence_ref": self.evidence_ref,
            "model_version": self.model_version,
        }


def _objective_met(objective: Mapping[str, Any], current_value: float) -> bool:
    comparison = objective.get("comparison")
    threshold = objective.get("threshold")
    if not isinstance(threshold, int | float):
        return False
    if comparison == "below":
        return current_value <= threshold
    if comparison == "above":
        return current_value >= threshold
    return False


def evaluate_plan(
    prior_items: Sequence[Mapping[str, Any]],
    current_facts: Mapping[str, Mapping[str, Any]],
    *,
    evidence_ref: str,
) -> list[PlanEvaluation]:
    """One PlanEvaluation per prior plan item with a currently-measurable metric."""
    evaluations: list[PlanEvaluation] = []
    for item in prior_items:
        objective = item.get("objective")
        target_ref = item.get("target_ref")
        if not isinstance(objective, Mapping) or not isinstance(target_ref, str):
            continue
        metric_id = objective.get("metric_id")
        fact = current_facts.get(metric_id) if isinstance(metric_id, str) else None
        current_value = fact.get("value") if isinstance(fact, Mapping) else None
        if not isinstance(current_value, int | float):
            continue
        evaluations.append(
            PlanEvaluation(
                target_ref=target_ref,
                met=_objective_met(objective, float(current_value)),
                evidence_ref=evidence_ref,
            )
        )
    return evaluations


def adaptation_multiplier(evaluations: Sequence[PlanEvaluation], *, target_ref: str) -> float:
    """1.0 (no adaptation) unless ``target_ref`` was evaluated and unmet."""
    for evaluation in evaluations:
        if evaluation.target_ref == target_ref and not evaluation.met:
            return UNMET_TARGET_BOOST
    return 1.0
