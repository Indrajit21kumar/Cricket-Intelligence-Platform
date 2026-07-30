"""Legend Similarity Score (M15 Step 4, FR-M15-04/05, Book 5 Ch. 6).

For each legend-style benchmark profile, compare the player's facts against
its target ranges (the same per-metric comparison as Step 3) and aggregate
into a similarity percentage — nearer the ranges, higher the similarity.
Returns the ranked styles PLUS the metric comparisons driving each score,
sorted most-explanatory first: Book 5 Ch. 6 and FR-M15-05 both require every
similarity figure to carry its explanation, never a bare percentage.

Aggregation method (:data:`SIMILARITY_METHOD_VERSION`, an explicit,
versioned engineering choice the spec leaves open — same practice as M14's
scoring.py): each compared metric contributes 100% when within its target
range, decaying linearly with distance past the range's ``spread`` once
outside it, floored at 0%; a style's similarity is the mean across its
compared metrics.

A legend-style profile with NO metric overlapping the player's facts cannot
be scored at all — it is omitted from the ranking, never guessed at.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchmark_service.domain.comparison import (
    NEAR,
    OUTSIDE,
    WITHIN,
    MetricComparison,
    compare_metrics,
)
from benchmark_service.domain.profiles import LEGEND_STYLE, BenchmarkProfile

SIMILARITY_METHOD_VERSION = "legend-similarity-1.0.0"

#: Similarity points lost per one "spread" of distance past the range edge.
_DECAY_PER_SPREAD = 50.0

_SEVERITY_RANK = {OUTSIDE: 0, NEAR: 1, WITHIN: 2}


class EndorsementGuardrailError(ValueError):
    """Raised when a Legend Similarity figure would be emitted without driving gaps.

    Book 0 SS11.2 / FR-M15-05 / AC-M15-04: a bare percentage is never
    emitted. :func:`score_style` already never constructs an empty-gaps
    result (Step 4's logic), but this makes it a hard, unbypassable
    invariant of the dataclass itself (Step 6) rather than an emergent
    property of one call site — the same structural pattern M14's
    ``LegendStyleComparison`` uses for the identical guarantee.
    """


@dataclass(frozen=True, slots=True)
class LegendStyleResult:
    """One style's similarity score — never without its driving comparisons."""

    style_label: str
    similarity: float
    driving_gaps: tuple[MetricComparison, ...]
    confidence: float | None

    def __post_init__(self) -> None:
        if not self.driving_gaps:
            raise EndorsementGuardrailError(
                "a Legend Similarity figure must never be emitted without its "
                "driving gaps (Book 0 SS11.2 / FR-M15-05)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_label": self.style_label,
            "similarity": round(self.similarity, 1),
            "driving_gaps": [gap.to_dict() for gap in self.driving_gaps],
            "confidence": self.confidence,
        }


def _distance_from_range(comparison: MetricComparison) -> float:
    low, high = comparison.target_range
    if low <= comparison.value <= high:
        return 0.0
    return low - comparison.value if comparison.value < low else comparison.value - high


def _sort_key(comparison: MetricComparison) -> tuple[int, float]:
    return (_SEVERITY_RANK[comparison.classification], -_distance_from_range(comparison))


def _metric_similarity(comparison: MetricComparison, spread: float) -> float:
    if comparison.classification == WITHIN:
        return 100.0
    distance = _distance_from_range(comparison)
    if spread <= 0:
        return 0.0
    return max(0.0, 100.0 - (distance / spread) * _DECAY_PER_SPREAD)


def _style_label(profile: BenchmarkProfile) -> str:
    label = profile.scope.get("label")
    return str(label) if isinstance(label, str) else profile.benchmark_id


def _style_confidence(comparisons: Sequence[MetricComparison]) -> float | None:
    confidences = [c.confidence for c in comparisons if c.confidence is not None]
    return sum(confidences) / len(confidences) if confidences else None


def score_style(
    facts: Mapping[str, Mapping[str, Any]], profile: BenchmarkProfile
) -> LegendStyleResult | None:
    """Score one legend-style profile, or None when nothing is comparable."""
    comparisons = compare_metrics(facts, profile.distributions)
    if not comparisons:
        return None

    similarities = [
        _metric_similarity(c, float(profile.distributions[c.metric_id].get("spread", 0.0)))
        for c in comparisons
    ]
    similarity = sum(similarities) / len(similarities)
    driving_gaps = tuple(sorted(comparisons, key=_sort_key))

    return LegendStyleResult(
        style_label=_style_label(profile),
        similarity=similarity,
        driving_gaps=driving_gaps,
        confidence=_style_confidence(comparisons),
    )


def compute_legend_similarity(
    facts: Mapping[str, Mapping[str, Any]], profiles: Sequence[BenchmarkProfile]
) -> list[LegendStyleResult]:
    """Score + rank every legend-style profile with at least one comparable metric."""
    results = [
        result
        for profile in profiles
        if profile.type == LEGEND_STYLE and (result := score_style(facts, profile)) is not None
    ]
    return sorted(results, key=lambda r: r.similarity, reverse=True)
