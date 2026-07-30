"""The endorsement guardrail, enforced at the source (M15 Step 6, §11, AC-M15-05).

Book 0 SS11.2 / TRUST-002 (binding, not overridable by configuration):
legend-style benchmarks are reference models derived from publicly
observable technique. CIP MUST NOT claim endorsement by, or use
proprietary/licensed data of, any named professional. The Legend Similarity
Score compares across several styles and explains gaps — it never asserts a
professional's involvement.

M15 enforces this at the source (this module), M14 renders it (its own,
independently-scoped ``DISCLAIMER`` + ``EndorsementGuardrailError`` in
``report_service.domain.legend``) — defense in depth: even if a future bug
in M14's rendering dropped the disclaimer, the data M15 actually publishes
and persists already carries it, and :mod:`legend_similarity`'s
``LegendStyleResult`` already cannot be constructed without driving gaps.

The disclaimer is a fixed module constant, never a caller-supplied
parameter: there is no code path that builds a :class:`LegendSimilarityView`
without it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from benchmark_service.domain.legend_similarity import LegendStyleResult

DISCLAIMER = (
    "Legend-style benchmarks are reference models derived from publicly observable "
    "technique. CIP does not claim endorsement by, or use proprietary or licensed "
    "data of, any named professional (Book 0 SS11.2)."
)


@dataclass(frozen=True, slots=True)
class LegendSimilarityView:
    """The publishable/persistable Legend Similarity payload — always guarded."""

    styles: tuple[LegendStyleResult, ...]
    benchmark_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "styles": [style.to_dict() for style in self.styles],
            "benchmark_version": self.benchmark_version,
            "disclaimer": DISCLAIMER,
        }


def build_legend_similarity_view(
    results: Sequence[LegendStyleResult], *, benchmark_version: str
) -> LegendSimilarityView | None:
    """Wrap ranked results for publish/persist, or None when there's nothing to show.

    Every :class:`LegendStyleResult` inside already carries its own driving
    gaps (enforced at construction) — this just adds the pinned benchmark
    version and the disclaimer that can never be omitted from the output.
    """
    if not results:
        return None
    return LegendSimilarityView(styles=tuple(results), benchmark_version=benchmark_version)
