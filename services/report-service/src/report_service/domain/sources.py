"""Input source adapters (M14 Step 2+, §10).

report-service assembles a report from several upstream reads. Each is a seam,
following the "adapters + fakes, defer real infra" pattern used throughout the
platform (M05's VideoProcessor/ProfileClient, M07's BatDetector, ...): a real
implementation is deferred, a deterministic fake lets the assembly + guardrail
logic be built and tested now.

- :class:`HistorySource` — the player's own longitudinal baseline (M04 Cricket
  DNA), for the Improvement score (Book 4 Ch. 8). M04 exists as a module, but
  the cross-service fetch is deferred like every other adapter in this build.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


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
