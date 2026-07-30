"""Personal-baseline comparison (M15 Step 5, FR-M15-06, AC-M15-07, Book 5 Ch. 3.3).

A different question from Step 3's benchmark comparison: not "how do I
compare to an external standard" but "am I improving relative to my own
past". The player's own historical distribution per CIP-STD metric is
maintained by Cricket DNA (M04) and fetched by :class:`PersonalBaselineSource`
— a fan-in read by person_id, same "adapters + fakes, defer real infra"
pattern used throughout this platform, since M04's cross-service fetch isn't
wired up yet.

Whether a delta is an improvement depends on knowing which direction is
better for that metric — the same ambiguity M14's scoring.py resolved with
an explicit ``HIGHER_IS_BETTER`` allow-list (Book 4 Ch. 8's Improvement
score). This module makes the identical, independently-scoped decision for
the same metric IDs: a metric absent from the allow-list gets an honest
``"unknown"`` direction rather than a guessed one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

IMPROVED = "improved"
REGRESSED = "regressed"
STABLE = "stable"
UNKNOWN_DIRECTION = "unknown"

# True = a higher value is better for this metric. Same convention + same
# metric IDs M14's scoring.py established for Book 4 Ch. 8's Improvement
# score; a metric outside this set has no known direction.
HIGHER_IS_BETTER: dict[str, bool] = {
    "BM-01": False,
    "BM-04": True,
    "BM-12": True,
    "BM-14": False,
    "BM-16": False,
    "PH-01": True,
    "PH-08": True,
}


@dataclass(frozen=True, slots=True)
class PersonalBaseline:
    """A player's own historical distribution for one CIP-STD metric."""

    metric_id: str
    mean: float
    stddev: float = 0.0
    count: int = 0


class PersonalBaselineSource(Protocol):
    async def load(self, person_id: str) -> list[PersonalBaseline]:
        """The player's stored baselines, or [] when there is no history yet."""
        ...


class FakePersonalBaselineSource:
    """In-process personal-baseline source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.baselines: dict[str, list[PersonalBaseline]] = {}

    def set_baselines(self, person_id: str, baselines: list[PersonalBaseline]) -> None:
        self.baselines[person_id] = baselines

    async def load(self, person_id: str) -> list[PersonalBaseline]:
        return self.baselines.get(person_id, [])


@dataclass(frozen=True, slots=True)
class PersonalComparison:
    """One metric's change relative to the player's own history."""

    metric_id: str
    value: float
    baseline_mean: float
    delta: float
    direction: str
    confidence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "baseline_mean": self.baseline_mean,
            "delta": self.delta,
            "direction": self.direction,
            "confidence": self.confidence,
        }


def _direction(metric_id: str, delta: float) -> str:
    higher_is_better = HIGHER_IS_BETTER.get(metric_id)
    if higher_is_better is None:
        return UNKNOWN_DIRECTION
    if delta == 0:
        return STABLE
    improved = delta > 0 if higher_is_better else delta < 0
    return IMPROVED if improved else REGRESSED


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def compare_to_baseline(
    facts: Mapping[str, Mapping[str, Any]],
    baselines: Sequence[PersonalBaseline],
) -> list[PersonalComparison]:
    """One comparison per metric present in both the facts and the baselines."""
    results: list[PersonalComparison] = []
    for baseline in baselines:
        fact = facts.get(baseline.metric_id)
        if fact is None:
            continue
        value = _as_float(fact.get("value"))
        if value is None:
            continue
        delta = value - baseline.mean
        results.append(
            PersonalComparison(
                metric_id=baseline.metric_id,
                value=value,
                baseline_mean=baseline.mean,
                delta=delta,
                direction=_direction(baseline.metric_id, delta),
                confidence=_as_float(fact.get("confidence")),
            )
        )
    return results
