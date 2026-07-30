"""Per-metric comparison + gap explanation (M15 Step 3, FR-M15-02/03/07, §5).

For each CIP-STD metric present in BOTH the player's facts (M10/M11) and a
benchmark profile's distributions, compute the distance to the target range,
classify within/near/outside, and produce a coaching-oriented gap
description — never a bare delta (FR-M15-03). Confidence + provenance
propagate from the input metric into the comparison (FR-M15-07): a
comparison is never firmer than the fact it's built from.

This module compares against ONE profile's distributions (the primary
skill-tier or age-band benchmark selected in Step 2). Legend-style profiles
use a related but distinct aggregation — the Legend Similarity Score
(Step 4) — because "how close am I to this style overall" is a different
question from "where do I sit on this one metric".

A metric absent from either side is skipped, not guessed at: comparison
requires both a measured/estimated value and a target range to mean
anything.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

WITHIN = "within"
NEAR = "near"
OUTSIDE = "outside"


@dataclass(frozen=True, slots=True)
class MetricComparison:
    """One metric's classified distance from a benchmark's target range."""

    metric_id: str
    value: float
    classification: str
    gap: str
    target_range: tuple[float, float]
    confidence: float | None
    provenance: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "classification": self.classification,
            "gap": self.gap,
            "target_range": list(self.target_range),
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


def _classify(value: float, low: float, high: float, spread: float) -> str:
    if low <= value <= high:
        return WITHIN
    distance = low - value if value < low else value - high
    return NEAR if distance <= spread else OUTSIDE


def _gap_description(
    metric_id: str, value: float, low: float, high: float, classification: str
) -> str:
    range_text = f"{low:g}-{high:g}"
    if classification == WITHIN:
        return f"{metric_id} ({value:g}) is within the benchmark range ({range_text})."
    direction = "below" if value < low else "above"
    edge = low if value < low else high
    distance = abs(value - edge)
    qualifier = "just outside" if classification == NEAR else "well outside"
    return (
        f"{metric_id} ({value:g}) is {qualifier} the benchmark range ({range_text}) — "
        f"{distance:g} {direction} the nearer edge."
    )


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def compare_metric(
    metric_id: str,
    fact: Mapping[str, Any],
    distribution: Mapping[str, Any],
) -> MetricComparison | None:
    """One metric's comparison, or None when there's nothing to compare."""
    value = _as_float(fact.get("value"))
    target_range = distribution.get("range")
    if value is None or not (isinstance(target_range, Sequence) and len(target_range) == 2):
        return None

    low, high = float(target_range[0]), float(target_range[1])
    spread = _as_float(distribution.get("spread")) or 0.0
    classification = _classify(value, low, high, spread)

    return MetricComparison(
        metric_id=metric_id,
        value=value,
        classification=classification,
        gap=_gap_description(metric_id, value, low, high, classification),
        target_range=(low, high),
        confidence=_as_float(fact.get("confidence")),
        provenance=fact.get("provenance") if isinstance(fact.get("provenance"), str) else None,
    )


def compare_metrics(
    facts: Mapping[str, Mapping[str, Any]],
    distributions: Mapping[str, Mapping[str, Any]],
) -> list[MetricComparison]:
    """One comparison per metric present in both the facts and the distributions."""
    comparisons = []
    for metric_id, distribution in distributions.items():
        fact = facts.get(metric_id)
        if fact is None:
            continue
        comparison = compare_metric(metric_id, fact, distribution)
        if comparison is not None:
            comparisons.append(comparison)
    return comparisons
