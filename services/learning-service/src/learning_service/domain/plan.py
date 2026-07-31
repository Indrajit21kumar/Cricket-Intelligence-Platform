"""Plan assembly + dose/timeline tuning to learning speed (M17 Step 5, FR-M17-04, AC-M17-04).

Dose (reps x sets) and timeline scale INVERSELY with learning speed: a
faster-improving player needs FEWER repetitions and a SHORTER timeline to
reach the same measurable objective than a slower-improving one — "faster
learners progress quicker" read literally. Learning speed reuses Step 2's
``compute_improvement_rate`` signal (the mean magnitude of recent M16 trait
deltas) rather than a ``trait.learning_speed`` M16 never actually writes.

Base doses (:data:`BASE_REPS`/:data:`BASE_SETS`/:data:`BASE_TIMELINE_DAYS`)
and the reference rate the multiplier is computed against are explicit,
versioned engineering choices — SR-005 gives one worked example ("3x20
cover drives"), not a general formula.

Longitudinal planning (SR-001) is a property of the SYSTEM, not this one
pure function: plans persist as append-only history (migration 0001) and
Step 6's evaluation loop builds each new plan on the prior one's outcome,
rather than this module reasoning about history itself.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from learning_service.domain.drills import SelectedDrill

PLAN_MODEL_VERSION = "training-plan-1.0.0"

BASE_REPS = 20
BASE_SETS = 3
BASE_TIMELINE_DAYS = 14

MIN_DOSE_MULTIPLIER = 0.5
MAX_DOSE_MULTIPLIER = 2.0

#: The improvement_rate a dose multiplier of 1.0 (baseline dose) corresponds
#: to — an explicit reference point since Book 1 gives no numeric baseline.
REFERENCE_IMPROVEMENT_RATE = 0.15


@dataclass(frozen=True, slots=True)
class Dose:
    """A measurable practice dose — never a bare instruction."""

    reps: int
    sets: int
    timeline_days: int

    def to_dict(self) -> dict[str, Any]:
        return {"reps": self.reps, "sets": self.sets, "timeline_days": self.timeline_days}


@dataclass(frozen=True, slots=True)
class PlanItem:
    """One drill in the plan, doubling as its own explainability link (NFR-M17-04)."""

    finding_ref: str
    drill_name: str
    objective: dict[str, Any]
    dose: Dose
    target_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_ref": self.finding_ref,
            "drill_name": self.drill_name,
            "objective": self.objective,
            "dose": self.dose.to_dict(),
            "target_ref": self.target_ref,
        }


@dataclass(frozen=True, slots=True)
class TrainingPlan:
    stage: str
    items: tuple[PlanItem, ...]
    learning_speed: float | None
    model_version: str = PLAN_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "items": [item.to_dict() for item in self.items],
            "learning_speed": self.learning_speed,
            "model_version": self.model_version,
        }


def _dose_multiplier(learning_speed: float | None) -> float:
    """Higher learning_speed (faster improvement) -> lower multiplier (less dose needed).

    Unknown or fully-stalled (<=0) learning speed uses the baseline dose
    rather than guessing at a discount or a penalty.
    """
    if learning_speed is None or learning_speed <= 0:
        return 1.0
    ratio = REFERENCE_IMPROVEMENT_RATE / learning_speed
    return max(MIN_DOSE_MULTIPLIER, min(MAX_DOSE_MULTIPLIER, ratio))


def _tune_dose(multiplier: float) -> Dose:
    return Dose(
        reps=max(1, round(BASE_REPS * multiplier)),
        sets=max(1, round(BASE_SETS * multiplier)),
        timeline_days=max(1, round(BASE_TIMELINE_DAYS * multiplier)),
    )


def assemble_plan(
    selected_drills: Sequence[SelectedDrill], *, stage: str, learning_speed: float | None
) -> TrainingPlan:
    """Build the training plan: every selected drill, dosed to learning speed."""
    multiplier = _dose_multiplier(learning_speed)
    dose = _tune_dose(multiplier)
    items = tuple(
        PlanItem(
            finding_ref=drill.finding_id,
            drill_name=drill.drill_name,
            objective=drill.objective.to_dict(),
            dose=dose,
            target_ref=f"{drill.finding_id}:{drill.objective.metric_id}",
        )
        for drill in selected_drills
    )
    return TrainingPlan(stage=stage, items=items, learning_speed=learning_speed)
