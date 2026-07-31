"""Input source adapters (M18 Steps 2 + 4, §8).

academy-service composes rosters and dashboards from several upstream
reads. Each is a seam, following the "adapters + fakes, defer real infra"
pattern used throughout this platform: a real implementation is deferred, a
deterministic fake lets the pipeline be built and tested now — even for M02,
which physically exists in this repo, since no service in this build has
ever made a real cross-service HTTP call (consistency over convenience).

- :class:`RosterSource` — M02's tenant memberships (who is a player in this
  academy), the roster's ground truth.
- :class:`ReportScoreSource` — M14's latest report ``Scores`` for a player
  (``services/report-service/domain/scoring.py::Scores.to_dict()`` shape),
  or ``None`` when no report exists yet.
- :class:`DNATraitSource` — M16's current trait state for a player, keyed
  by ``trait_key`` (mirrors ``dna-service``'s ``DNAReader.read_traits``
  shape), or ``{}`` when M16 has never written a trait for them.
- :class:`ActivePlanSource` — M17's active ``training_plans`` row for a
  player (``TrainingPlan.to_dict()`` shape), or ``None`` when none is
  active. "Active" is M17's own persistence-layer concept
  (``plans_repo.get_active_plan``), not recomputed here.

Every payload crossing one of these seams is an opaque ``Mapping[str,
Any]`` — M18 composes it into a dashboard without interpreting or
recomputing any of it, matching its own scope boundary (§3.2, "computes no
cricket analysis of its own").
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RosterMember:
    """One M02 tenant membership relevant to the roster."""

    person_id: uuid.UUID
    role: str
    display_name: str | None = None


class RosterSource(Protocol):
    async def load(self, tenant_id: uuid.UUID) -> list[RosterMember]:
        """Every current member of this tenant (players and staff), or []."""
        ...


class FakeRosterSource:
    """In-process roster source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.members: dict[uuid.UUID, list[RosterMember]] = {}

    def set_members(self, tenant_id: uuid.UUID, members: list[RosterMember]) -> None:
        self.members[tenant_id] = members

    async def load(self, tenant_id: uuid.UUID) -> list[RosterMember]:
        return self.members.get(tenant_id, [])


class ReportScoreSource(Protocol):
    async def load(self, person_id: str) -> Mapping[str, Any] | None:
        """M14's latest report scores for this player, or None if no report yet."""
        ...


class FakeReportScoreSource:
    """In-process report-score source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.scores: dict[str, Mapping[str, Any]] = {}

    def set_scores(self, person_id: str, scores: Mapping[str, Any]) -> None:
        self.scores[person_id] = scores

    async def load(self, person_id: str) -> Mapping[str, Any] | None:
        return self.scores.get(person_id)


class DNATraitSource(Protocol):
    async def load(self, person_id: str) -> dict[str, Mapping[str, Any]]:
        """M16's current trait state for this player, keyed by trait_key; {} if none yet."""
        ...


class FakeDNATraitSource:
    """In-process DNA-trait source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.traits: dict[str, dict[str, Mapping[str, Any]]] = {}

    def set_traits(self, person_id: str, traits: dict[str, Mapping[str, Any]]) -> None:
        self.traits[person_id] = traits

    async def load(self, person_id: str) -> dict[str, Mapping[str, Any]]:
        return self.traits.get(person_id, {})


class ActivePlanSource(Protocol):
    async def load(self, person_id: str) -> Mapping[str, Any] | None:
        """M17's active training plan for this player, or None if none is active."""
        ...


class FakeActivePlanSource:
    """In-process active-plan source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.plans: dict[str, Mapping[str, Any]] = {}

    def set_plan(self, person_id: str, plan: Mapping[str, Any]) -> None:
        self.plans[person_id] = plan

    async def load(self, person_id: str) -> Mapping[str, Any] | None:
        return self.plans.get(person_id)
