"""Learning-stage inference (M17 Step 2, FR-M17-01, Book 1 Ch. 4.7).

Book 1 Ch. 4.7 names the signals qualitatively (cognitive = "high
variability, high error rate"; associative = "reducing errors, rising
consistency"; autonomous = "stable, automatic execution") but not
numerically — the thresholds below are an explicit, versioned engineering
choice, the same practice as every other spec gap this build fills in
(M14's scoring model, M15's similarity decay).

M17's own dependency list names ``trait.learning_speed``/``trait.consistency``
as M16 DNA inputs, but M16 Step 2 explicitly never computes those traits —
no established, measured signal exists for them anywhere in this codebase
(the same reasoning that excluded ``trait.aggression``). Rather than reading
values M16 never writes, this module computes its own, independently-scoped
proxies from data this build genuinely has:

- **Consistency** from the player's recent metric deviations against their
  M04 personal baseline (the same baseline shape M15 already established:
  mean/stddev per metric) — a low mean deviation means stable, repeatable
  execution.
- **Improvement rate** from M16's own trait-update history
  (``dna_update_runs``) — the mean magnitude of recent ``|new_value -
  prior_value|`` deltas Step 3 of M16 already computes and persists. Near
  zero means the trait has stabilised (an autonomous-stage signal); large
  and still moving means the player is still developing it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

COGNITIVE = "cognitive"
ASSOCIATIVE = "associative"
AUTONOMOUS = "autonomous"

STAGE_MODEL_VERSION = "learning-stage-1.0.0"

#: A player with no signal at all defaults to Cognitive — the conservative
#: assumption (never assume more mastery than evidenced).
DEFAULT_STAGE = COGNITIVE

#: Consistency (0-1, higher = steadier) at or above this crosses from
#: Cognitive into Associative.
CONSISTENCY_ASSOCIATIVE_THRESHOLD = 0.5
#: Consistency at or above this, combined with a stabilised improvement
#: rate, crosses into Autonomous.
CONSISTENCY_AUTONOMOUS_THRESHOLD = 0.8
#: An improvement rate below this magnitude counts as "stabilised" for the
#: Autonomous signal (traits have stopped moving much session to session).
IMPROVEMENT_STABLE_THRESHOLD = 0.05


def compute_consistency(deviations: Sequence[float]) -> float | None:
    """Consistency from recent per-metric deviations against personal baseline.

    Each ``deviation`` is a z-score-like ratio, ``(value - baseline_mean) /
    baseline_stddev``, one per recent observation (caller assembles these
    from M04's ``PersonalBaseline`` records). Bounded in (0, 1]; 1.0 means
    zero deviation, approaching 0 as deviations grow large. None (not 0) when
    there is no history at all — honestly unknown, not "inconsistent".
    """
    if not deviations:
        return None
    mean_abs_deviation = sum(abs(d) for d in deviations) / len(deviations)
    return 1.0 / (1.0 + mean_abs_deviation)


def compute_improvement_rate(trait_deltas: Sequence[float]) -> float | None:
    """Mean magnitude of recent trait-value changes (a learning-speed/stability proxy).

    Each delta is one session's ``|new_value - prior_value|`` from M16's own
    ``TraitUpdateResult`` history. None when there is no update history yet.
    """
    if not trait_deltas:
        return None
    return sum(abs(d) for d in trait_deltas) / len(trait_deltas)


@dataclass(frozen=True, slots=True)
class LearningSignals:
    """The two computed signals stage inference reads."""

    consistency: float | None
    improvement_rate: float | None


@dataclass(frozen=True, slots=True)
class StageEstimate:
    """The inferred stage plus the signals that produced it (explainability)."""

    stage: str
    consistency: float | None
    improvement_rate: float | None
    model_version: str = STAGE_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "consistency": self.consistency,
            "improvement_rate": self.improvement_rate,
            "model_version": self.model_version,
        }


def infer_stage(signals: LearningSignals) -> StageEstimate:
    """Estimate cognitive/associative/autonomous from the available signals."""
    if signals.consistency is None:
        return StageEstimate(
            stage=DEFAULT_STAGE, consistency=None, improvement_rate=signals.improvement_rate
        )

    stabilised = (
        signals.improvement_rate is not None
        and signals.improvement_rate < IMPROVEMENT_STABLE_THRESHOLD
    )

    if signals.consistency >= CONSISTENCY_AUTONOMOUS_THRESHOLD and stabilised:
        stage = AUTONOMOUS
    elif signals.consistency >= CONSISTENCY_ASSOCIATIVE_THRESHOLD:
        stage = ASSOCIATIVE
    else:
        stage = COGNITIVE

    return StageEstimate(
        stage=stage, consistency=signals.consistency, improvement_rate=signals.improvement_rate
    )
