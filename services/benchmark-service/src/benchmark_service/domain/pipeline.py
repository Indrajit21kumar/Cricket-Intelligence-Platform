"""Comparison pipeline — pure orchestration (M15 Step 7).

Combines Steps 2-6 into one comparison: select applicable profiles
(Step 2), compare per-metric against the primary tier/age profile (Step 3)
enriched with personal-baseline context per metric (Step 5), and score
Legend Similarity across the selected legend-style profiles (Step 4),
wrapped by the endorsement guardrail (Step 6).

``benchmark_version`` pins EVERY profile actually used (the primary
comparison profile plus every scored legend style) as a deterministic
composite string, e.g. ``"BN-LEGEND-X@2;BN-TIER-ADV-COVERDRIVE@1"``
(FR-M15-08) — reproducible given the same facts + profile set
(NFR-M15-02).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from benchmark_service.domain.comparison import MetricComparison, compare_metrics
from benchmark_service.domain.endorsement import build_legend_similarity_view
from benchmark_service.domain.legend_similarity import compute_legend_similarity
from benchmark_service.domain.personal_baseline import PersonalBaseline, compare_to_baseline
from benchmark_service.domain.profiles import (
    AGE_BAND,
    LEGEND_STYLE,
    SKILL_TIER,
    BenchmarkProfile,
    select_profiles,
)

SCHEMA_VERSION = "benchmark.compared/1.0"


@dataclass(frozen=True, slots=True)
class ComparisonResult:
    correlation_id: str
    person_id: str | None
    per_metric: list[dict[str, Any]]
    legend_similarity: dict[str, Any] | None
    benchmark_version: str
    confidence: float | None
    schema_version: str = SCHEMA_VERSION
    provisional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "person_id": self.person_id,
            "per_metric": self.per_metric,
            "legend_similarity": self.legend_similarity,
            "benchmark_version": self.benchmark_version,
            "confidence": self.confidence,
            "schema_version": self.schema_version,
            "provisional": self.provisional,
        }


def _primary_profile(selected: Sequence[BenchmarkProfile]) -> BenchmarkProfile | None:
    """Skill-tier is the primary per-metric comparison target, age-band the fallback.

    Book 5 Ch. 4 frames skill-tier as "the primary, safest benchmark" — an
    explicit, versioned choice, like every ambiguity this spec leaves open.
    """
    for profile in selected:
        if profile.type == SKILL_TIER:
            return profile
    for profile in selected:
        if profile.type == AGE_BAND:
            return profile
    return None


def _pin_version(profiles: Sequence[BenchmarkProfile]) -> str:
    """A deterministic composite of every profile version actually used (FR-M15-08)."""
    if not profiles:
        return "none"
    return ";".join(sorted(f"{p.benchmark_id}@{p.version}" for p in profiles))


def _merge_personal_baseline(
    per_metric: Sequence[MetricComparison],
    baseline_comparisons: Sequence[Any],
) -> list[dict[str, Any]]:
    baseline_by_metric = {b.metric_id: b for b in baseline_comparisons}
    merged = []
    for comparison in per_metric:
        payload = comparison.to_dict()
        baseline = baseline_by_metric.get(comparison.metric_id)
        payload["personal_baseline"] = baseline.to_dict() if baseline is not None else None
        merged.append(payload)
    return merged


def _mean_confidence(comparisons: Sequence[MetricComparison]) -> float | None:
    confidences = [c.confidence for c in comparisons if c.confidence is not None]
    return sum(confidences) / len(confidences) if confidences else None


def compute_comparison(
    *,
    correlation_id: str,
    person_id: str | None,
    facts: Mapping[str, Mapping[str, Any]],
    all_profiles: Sequence[BenchmarkProfile],
    shot_type: str,
    skill_tier: str | None,
    age_band: str | None,
    personal_baselines: Sequence[PersonalBaseline] = (),
) -> ComparisonResult:
    """Assemble one stroke's comparison from facts + profiles + personal history."""
    selected = select_profiles(
        all_profiles, shot_type=shot_type, skill_tier=skill_tier, age_band=age_band
    )

    primary = _primary_profile(selected)
    per_metric_comparisons = (
        compare_metrics(facts, primary.distributions) if primary is not None else []
    )
    baseline_comparisons = compare_to_baseline(facts, personal_baselines)
    per_metric = _merge_personal_baseline(per_metric_comparisons, baseline_comparisons)

    legend_profiles = [p for p in selected if p.type == LEGEND_STYLE]
    legend_results = compute_legend_similarity(facts, legend_profiles)

    used_profiles = ([primary] if primary is not None else []) + legend_profiles
    pinned_version = _pin_version(used_profiles)
    view = build_legend_similarity_view(legend_results, benchmark_version=pinned_version)

    return ComparisonResult(
        correlation_id=correlation_id,
        person_id=person_id,
        per_metric=per_metric,
        legend_similarity=view.to_dict() if view is not None else None,
        benchmark_version=pinned_version,
        confidence=_mean_confidence(per_metric_comparisons),
    )
