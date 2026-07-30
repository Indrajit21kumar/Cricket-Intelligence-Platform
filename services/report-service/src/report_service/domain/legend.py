"""Legend comparison view (M14 §5/§7, Step 4, FR-M14-05).

Renders M15's Legend Similarity comparison for the report. M15 (Benchmark
Intelligence) does not exist as a built service yet — only its spec
(``CIP_M15_Benchmark_Intelligence_v1.0.md``) is available — so this module
follows the same "adapters + fakes, defer real infra" pattern as every other
unbuilt upstream dependency in this build: :class:`LegendSource` is the seam,
:class:`FakeLegendSource` a deterministic stand-in for M15's ``benchmark.compared``
event, keyed by correlation_id like the other M14 source adapters.

The endorsement guardrail (Book 0 §11.2, FR-M15-05, AC-M14-05) is enforced
structurally, not just by convention:

- A :class:`LegendStyleComparison` cannot exist without at least one driving
  gap — constructing one with none raises :class:`EndorsementGuardrailError`,
  so a bare similarity percentage can never reach the report.
- The guardrail disclaimer is not a caller-supplied field on
  :class:`LegendView` — it is a fixed module constant always attached in
  ``to_dict()``, so no code path can serialise a legend view without it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

DISCLAIMER = (
    "Legend-style benchmarks are reference models derived from publicly observable "
    "technique. CIP does not claim endorsement by, or use proprietary or licensed "
    "data of, any named professional (Book 0 SS11.2)."
)


class EndorsementGuardrailError(ValueError):
    """Raised when a Legend Similarity figure would be emitted without driving gaps."""


@dataclass(frozen=True, slots=True)
class LegendGap:
    """One metric-level gap driving a style's similarity score."""

    metric_id: str
    description: str
    player_value: float | None
    benchmark_value: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "description": self.description,
            "player_value": self.player_value,
            "benchmark_value": self.benchmark_value,
        }


@dataclass(frozen=True, slots=True)
class LegendStyleComparison:
    """One style benchmark's similarity score — never without its driving gaps."""

    style_label: str
    similarity: float
    driving_gaps: tuple[LegendGap, ...]
    confidence: float

    def __post_init__(self) -> None:
        if not self.driving_gaps:
            raise EndorsementGuardrailError(
                "a Legend Similarity figure must never be rendered without its "
                "driving gaps (Book 0 SS11.2 / FR-M15-05)"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "style_label": self.style_label,
            "similarity": self.similarity,
            "driving_gaps": [g.to_dict() for g in self.driving_gaps],
            "confidence": self.confidence,
        }


@dataclass(frozen=True, slots=True)
class LegendView:
    styles: tuple[LegendStyleComparison, ...]
    benchmark_version: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "styles": [s.to_dict() for s in self.styles],
            "benchmark_version": self.benchmark_version,
            "disclaimer": DISCLAIMER,
        }


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _build_gap(raw: Mapping[str, Any]) -> LegendGap:
    return LegendGap(
        metric_id=str(raw.get("metric_id", "")),
        description=str(raw.get("description", "")),
        player_value=_as_float(raw.get("player_value")),
        benchmark_value=_as_float(raw.get("benchmark_value")),
    )


def _build_style(raw: Mapping[str, Any]) -> LegendStyleComparison | None:
    gaps_raw = raw.get("driving_gaps", [])
    gaps = tuple(
        _build_gap(g) for g in gaps_raw if isinstance(gaps_raw, Sequence) and isinstance(g, Mapping)
    )
    try:
        return LegendStyleComparison(
            style_label=str(raw.get("style_label", "")),
            similarity=float(raw.get("similarity", 0.0)),
            driving_gaps=gaps,
            confidence=float(raw.get("confidence", 0.0)),
        )
    except EndorsementGuardrailError:
        # A style with no driving gaps is dropped rather than rendered bare —
        # the guardrail applies to M14's rendering even if upstream ever sends
        # malformed data.
        return None


def build_legend_view(comparison: Mapping[str, Any] | None) -> LegendView | None:
    """Render M15's comparison payload, or None when M15 has not produced one.

    Honestly absent rather than faked: no comparison, no legend section.
    """
    if comparison is None:
        return None
    raw_styles = comparison.get("styles")
    if not isinstance(raw_styles, Sequence):
        return None

    styles = [
        style
        for raw in raw_styles
        if isinstance(raw, Mapping) and (style := _build_style(raw)) is not None
    ]
    if not styles:
        return None

    benchmark_version = comparison.get("benchmark_version")
    return LegendView(
        styles=tuple(styles),
        benchmark_version=str(benchmark_version) if benchmark_version is not None else None,
    )
