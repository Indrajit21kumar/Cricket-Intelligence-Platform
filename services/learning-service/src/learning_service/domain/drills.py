"""Drill selection with measurable objectives (M17 Step 4, FR-M17-03/07, SR-005).

M17 never invents a drill: every selected drill's identity (name) comes
directly from the M13 finding it addresses — the same ``drill`` field M13's
rule-driven Finding assembly already attaches, itself traced to a grounded
M12 rule. M17's own job here is narrower: attach a MEASURABLE objective
(SR-005: "3x20 cover drives, head displacement <5cm") to that already-
grounded drill, using the target threshold M15's benchmark comparison
already computed for the same metric — never inventing a number either.

A prioritised fault whose finding has no ``drill`` field, no metric_id in
its evidence, or no M15 benchmark comparison for that metric is honestly
skipped rather than given a fabricated objective (FR-M17-07, AC-M17-06).

Dose (reps x sets) and timeline are NOT set here — that is Step 5's job,
tuned to the player's learning speed. This step decides WHAT the target is;
Step 5 decides how much practice reaches it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from learning_service.domain.prioritization import PrioritizedFault

DRILL_SELECTION_MODEL_VERSION = "drill-selection-1.0.0"

ABOVE = "above"
BELOW = "below"


@dataclass(frozen=True, slots=True)
class DrillObjective:
    """A quantified target for one metric — never a bare instruction."""

    metric_id: str
    comparison: str
    threshold: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "comparison": self.comparison,
            "threshold": self.threshold,
        }


@dataclass(frozen=True, slots=True)
class SelectedDrill:
    """One grounded drill + measurable objective, linked to its finding."""

    finding_id: str
    drill_name: str
    objective: DrillObjective
    priority_score: float
    model_version: str = DRILL_SELECTION_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "drill_name": self.drill_name,
            "objective": self.objective.to_dict(),
            "priority_score": self.priority_score,
            "model_version": self.model_version,
        }


def _drill_name(finding: Mapping[str, Any]) -> str | None:
    drill = finding.get("drill")
    name = drill.get("name") if isinstance(drill, Mapping) else None
    return name if isinstance(name, str) else None


def _primary_metric_id(finding: Mapping[str, Any]) -> str | None:
    evidence = finding.get("evidence", [])
    if not isinstance(evidence, Sequence):
        return None
    for item in evidence:
        metric_id = item.get("metric_id") if isinstance(item, Mapping) else None
        if isinstance(metric_id, str):
            return metric_id
    return None


def _objective_from_comparison(
    metric_id: str, comparison: Mapping[str, Any]
) -> DrillObjective | None:
    """The target threshold from M15's own per-metric target_range — never invented.

    Outside the range: cross the nearer edge. Already within range: refine
    toward the midpoint rather than reporting "nothing to work on" — a
    prioritised fault always gets an objective to aim at.
    """
    target_range = comparison.get("target_range")
    value = comparison.get("value")
    if not (
        isinstance(target_range, Sequence)
        and len(target_range) == 2
        and isinstance(value, int | float)
    ):
        return None

    low, high = float(target_range[0]), float(target_range[1])
    value = float(value)
    if value < low:
        return DrillObjective(metric_id=metric_id, comparison=ABOVE, threshold=low)
    if value > high:
        return DrillObjective(metric_id=metric_id, comparison=BELOW, threshold=high)
    midpoint = round((low + high) / 2, 2)
    direction = BELOW if value > midpoint else ABOVE
    return DrillObjective(metric_id=metric_id, comparison=direction, threshold=midpoint)


def select_drills(
    prioritized_faults: Sequence[PrioritizedFault],
    *,
    findings_by_id: Mapping[str, Mapping[str, Any]],
    benchmark_comparisons_by_metric: Mapping[str, Mapping[str, Any]],
) -> list[SelectedDrill]:
    """One SelectedDrill per prioritised fault with a grounded drill + measurable target.

    Order follows ``prioritized_faults`` (already ranked, Step 3). A fault
    that cannot be grounded end to end — drill, metric, and target — is
    skipped, never filled in with a guess.
    """
    selected: list[SelectedDrill] = []
    for fault in prioritized_faults:
        finding = findings_by_id.get(fault.finding_id)
        if finding is None:
            continue
        drill_name = _drill_name(finding)
        if drill_name is None:
            continue
        metric_id = _primary_metric_id(finding)
        if metric_id is None:
            continue
        comparison = benchmark_comparisons_by_metric.get(metric_id)
        if comparison is None:
            continue
        objective = _objective_from_comparison(metric_id, comparison)
        if objective is None:
            continue
        selected.append(
            SelectedDrill(
                finding_id=fault.finding_id,
                drill_name=drill_name,
                objective=objective,
                priority_score=fault.score,
            )
        )
    return selected
