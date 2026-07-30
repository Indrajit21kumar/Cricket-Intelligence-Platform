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

from typing import Protocol

from reasoning_service.domain.facts import FactSet


class FactSource(Protocol):
    async def load(self, correlation_id: str) -> FactSet | None:
        """Assemble the fact set for a stroke, or None when unavailable."""
        ...


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
