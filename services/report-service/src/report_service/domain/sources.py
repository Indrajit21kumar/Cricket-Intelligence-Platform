"""Input source adapters (M14 Step 2+, §10).

report-service assembles a report from several upstream reads. Each is a seam,
following the "adapters + fakes, defer real infra" pattern used throughout the
platform (M05's VideoProcessor/ProfileClient, M07's BatDetector, ...): a real
implementation is deferred, a deterministic fake lets the assembly + guardrail
logic be built and tested now.

- :class:`HistorySource` — the player's own longitudinal baseline (M04 Cricket
  DNA), for the Improvement score (Book 4 Ch. 8). M04 exists as a module, but
  the cross-service fetch is deferred like every other adapter in this build.
- :class:`LegendSource` — M15's ``benchmark.compared`` payload for the Legend
  comparison view (Step 4). M15 does not exist as a built service yet (only
  its spec), so this is a fan-in read keyed by correlation_id, same as the
  other cross-module fetches in this build.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PlayerHistory:
    """A player's prior baseline for one CIP-STD metric-derived score."""

    metric_key: str
    baseline_value: float
    baseline_confidence: float


class HistorySource(Protocol):
    async def load(self, person_id: str) -> list[PlayerHistory]:
        """The player's stored baselines, or [] when there is no history yet."""
        ...


class FakeHistorySource:
    """In-process history source holding baselines for dev + tests."""

    def __init__(self) -> None:
        self.histories: dict[str, list[PlayerHistory]] = {}

    def set_history(self, person_id: str, history: list[PlayerHistory]) -> None:
        self.histories[person_id] = history

    async def load(self, person_id: str) -> list[PlayerHistory]:
        return self.histories.get(person_id, [])


class LegendSource(Protocol):
    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        """M15's comparison payload for this stroke, or None if not yet produced."""
        ...


class FakeLegendSource:
    """In-process legend-comparison source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.comparisons: dict[str, Mapping[str, Any]] = {}

    def set_comparison(self, correlation_id: str, comparison: Mapping[str, Any]) -> None:
        self.comparisons[correlation_id] = comparison

    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        return self.comparisons.get(correlation_id)
