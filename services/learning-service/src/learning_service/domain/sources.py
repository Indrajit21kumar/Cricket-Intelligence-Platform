"""Input source adapters (M17 Step 7, §10).

learning-service assembles a plan from several upstream reads. Each is a
seam, following the "adapters + fakes, defer real infra" pattern used
throughout this platform: a real implementation is deferred, a
deterministic fake lets the pipeline be built and tested now.

- :class:`FindingsSource` — M13's findings for a stroke.
- :class:`BenchmarkComparisonSource` — M15's per-metric comparisons for a
  stroke (target ranges for drill objectives, current values for plan
  evaluation — one source serves both Step 4 and Step 6).
- :class:`DNAHistorySource` — M16's recent trait-update deltas for a
  player (Step 2's improvement-rate signal).
- :class:`PersonalDeviationSource` — M04's recent per-metric deviations
  against personal baseline for a player (Step 2's consistency signal).
- :class:`TenantResolver` — which tenant currently coaches this player.
  M16's ``dna.updated`` (M17's trigger) is person-scoped (NIL tenant
  sentinel, mirroring M04's own events) but ``training_plans`` is
  tenant-scoped personal data (§9) — this is the seam that resolves one
  from the other, standing in for a real M02 membership lookup.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Protocol


class FindingsSource(Protocol):
    async def load(self, session_ref: str) -> list[Mapping[str, Any]]:
        """M13's findings for this stroke, or [] when there are none."""
        ...


class FakeFindingsSource:
    def __init__(self) -> None:
        self.findings: dict[str, list[Mapping[str, Any]]] = {}

    def set_findings(self, session_ref: str, findings: list[Mapping[str, Any]]) -> None:
        self.findings[session_ref] = findings

    async def load(self, session_ref: str) -> list[Mapping[str, Any]]:
        return self.findings.get(session_ref, [])


class BenchmarkComparisonSource(Protocol):
    async def load(self, session_ref: str) -> dict[str, Mapping[str, Any]]:
        """M15's per-metric comparisons for this stroke, keyed by metric_id."""
        ...


class FakeBenchmarkComparisonSource:
    def __init__(self) -> None:
        self.comparisons: dict[str, dict[str, Mapping[str, Any]]] = {}

    def set_comparisons(self, session_ref: str, comparisons: dict[str, Mapping[str, Any]]) -> None:
        self.comparisons[session_ref] = comparisons

    async def load(self, session_ref: str) -> dict[str, Mapping[str, Any]]:
        return self.comparisons.get(session_ref, {})


class DNAHistorySource(Protocol):
    async def load(self, person_id: str) -> list[float]:
        """Recent |new_value - prior_value| trait deltas for this player."""
        ...


class FakeDNAHistorySource:
    def __init__(self) -> None:
        self.deltas: dict[str, list[float]] = {}

    def set_deltas(self, person_id: str, deltas: list[float]) -> None:
        self.deltas[person_id] = deltas

    async def load(self, person_id: str) -> list[float]:
        return self.deltas.get(person_id, [])


class PersonalDeviationSource(Protocol):
    async def load(self, person_id: str) -> list[float]:
        """Recent per-metric deviations against this player's personal baseline."""
        ...


class FakePersonalDeviationSource:
    def __init__(self) -> None:
        self.deviations: dict[str, list[float]] = {}

    def set_deviations(self, person_id: str, deviations: list[float]) -> None:
        self.deviations[person_id] = deviations

    async def load(self, person_id: str) -> list[float]:
        return self.deviations.get(person_id, [])


class TenantResolver(Protocol):
    async def resolve(self, person_id: str) -> uuid.UUID | None:
        """The tenant currently coaching this player, or None if unknown."""
        ...


class FakeTenantResolver:
    def __init__(self) -> None:
        self.tenants: dict[str, uuid.UUID] = {}

    def set_tenant(self, person_id: str, tenant_id: uuid.UUID) -> None:
        self.tenants[person_id] = tenant_id

    async def resolve(self, person_id: str) -> uuid.UUID | None:
        return self.tenants.get(person_id)
