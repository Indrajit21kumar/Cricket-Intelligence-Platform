"""Input source adapters (M15 Step 7, §10).

benchmark-service assembles a comparison from several upstream reads. Each
is a seam, following the "adapters + fakes, defer real infra" pattern used
throughout this platform: a real implementation is deferred, a
deterministic fake lets the pipeline be built and tested now.

- :class:`FactsSource` — the player's M10 biomechanics + M11 physics metric
  values for a stroke, fetched by correlation_id (the same fan-in read
  M13's FactSource made for reasoning).
- :class:`PlayerContextSource` — the M09 shot type + M04 skill tier/age band
  needed to select applicable benchmark profiles (Step 2).

Personal-baseline fetch (``personal_baseline.PersonalBaselineSource``) and
benchmark profile selection (this service's own global data, read directly
via :mod:`profiles_repo`, no fake needed) are handled elsewhere.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


class FactsSource(Protocol):
    async def load(self, correlation_id: str) -> dict[str, Mapping[str, Any]]:
        """The player's BM/PH metric facts for this stroke, or {} if unavailable."""
        ...


class FakeFactsSource:
    """In-process facts source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.facts: dict[str, dict[str, Mapping[str, Any]]] = {}

    def set_facts(self, correlation_id: str, facts: dict[str, Mapping[str, Any]]) -> None:
        self.facts[correlation_id] = facts

    async def load(self, correlation_id: str) -> dict[str, Mapping[str, Any]]:
        return self.facts.get(correlation_id, {})


@dataclass(frozen=True, slots=True)
class PlayerContext:
    """What benchmark selection needs to know about the stroke + the player."""

    shot_type: str
    skill_tier: str | None = None
    age_band: str | None = None


class PlayerContextSource(Protocol):
    async def load(self, correlation_id: str) -> PlayerContext | None:
        """The shot/tier/age context for this stroke, or None if unavailable."""
        ...


class FakePlayerContextSource:
    """In-process player-context source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.contexts: dict[str, PlayerContext] = {}

    def set_context(self, correlation_id: str, context: PlayerContext) -> None:
        self.contexts[correlation_id] = context

    async def load(self, correlation_id: str) -> PlayerContext | None:
        return self.contexts.get(correlation_id)
