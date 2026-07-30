"""Input source adapters (M13 Step 2-3, §4).

M13 needs two things to reason about a stroke: the FACTS (M10 biomechanics +
M11 physics + M09 shot context) and the KNOWLEDGE (the applicable released rules
from M12, with precedence). Each is a seam:

- :class:`FactSource` assembles a :class:`FactSet` by correlation_id. The real
  implementation reads the M10/M11/M09 outputs; the fake holds one a test
  provides, so the reasoning runs with no upstream service.

A None fact set means the analytics are not (yet) assembleable — nothing to
reason about — so M13 produces no result, which is correct.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from reasoning_service.domain.facts import FactSet


class FactSource(Protocol):
    async def load(self, correlation_id: str) -> FactSet | None:
        """Assemble the fact set for a stroke, or None when unavailable."""
        ...


@dataclass(frozen=True, slots=True)
class MatchResult:
    """The applicable released rules for a fact set, from M12's match API.

    ``kg_version`` pins the knowledge served, so M13's result is reproducible
    against the exact rules that produced it. ``conflicts`` carries M12's
    recorded precedence so M13 can resolve co-firing rules (Step 4).
    """

    kg_version: str
    rules: list[dict[str, Any]]
    conflicts: list[dict[str, Any]] = field(default_factory=list)


class KnowledgeSource(Protocol):
    async def match(self, facts_payload: dict[str, Any]) -> MatchResult:
        """Return the applicable RELEASED rules + kg_version for a fact set.

        The real implementation calls M12 ``POST /internal/kg/match`` (and reads
        its conflict precedence); M12 does the matching against the pinned graph,
        so knowledge stays in M12 and improving coaching is a data change there.
        """
        ...


class FakeKnowledgeSource:
    """In-process knowledge source holding a MatchResult for dev + tests."""

    def __init__(self, result: MatchResult | None = None) -> None:
        self.result = result or MatchResult(kg_version="kg@fake", rules=[])

    def set_result(self, result: MatchResult) -> None:
        self.result = result

    async def match(self, facts_payload: dict[str, Any]) -> MatchResult:
        return self.result


class FakeFactSource:
    """In-process fact source holding pre-assembled FactSets for dev + tests."""

    def __init__(self) -> None:
        self.fact_sets: dict[str, FactSet] = {}
        self.missing = False

    def set_facts(self, correlation_id: str, fact_set: FactSet) -> None:
        self.fact_sets[correlation_id] = fact_set

    async def load(self, correlation_id: str) -> FactSet | None:
        if self.missing:
            return None
        return self.fact_sets.get(correlation_id)
