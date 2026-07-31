"""Input source adapters (M18 Steps 2, 4 + 5, §8).

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
- :class:`CohortContextSource` — M04's ``skill_tier``/``age_band``
  attributes for a player, the same fairness axes M15 already established
  for benchmark selection (``benchmark_service.domain.sources.PlayerContext``)
  — reused here rather than invented, since "fair" leaderboard grouping
  means exactly what it means there.
- :class:`PlayerInsightsSource` — M16's resolved recurring weak areas /
  strengths for a player. M16's own ``dna.updated`` event payload already
  carries the resolved list per trait (``traits_updated["weak.areas"]
  ["recurring"]`` / ``traits_updated["trait.strengths"]["recurring"]`` —
  see ``dna_service.domain.inference.InferenceResult.to_dict``); this
  source stands in for the last such event observed per player, rather
  than re-deriving the recurrence count from M04's raw stored trait value
  (which would duplicate M16's own recurrence-threshold logic).
- :class:`LeaderboardOptInSource` — whether a player has explicitly opted
  in to appear on leaderboards (an M02-style consent read). Leaderboards
  are opt-in only: absence of a recorded opt-in means excluded, never
  defaulted to included.

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


@dataclass(frozen=True, slots=True)
class CohortContext:
    """A player's fairness-grouping attributes, from M04."""

    skill_tier: str | None = None
    age_band: str | None = None


class CohortContextSource(Protocol):
    async def load(self, person_id: str) -> CohortContext:
        """This player's skill_tier/age_band, or an all-None context if unset."""
        ...


class FakeCohortContextSource:
    """In-process cohort-context source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.contexts: dict[str, CohortContext] = {}

    def set_context(self, person_id: str, context: CohortContext) -> None:
        self.contexts[person_id] = context

    async def load(self, person_id: str) -> CohortContext:
        return self.contexts.get(person_id, CohortContext())


class PlayerInsightsSource(Protocol):
    async def load(self, person_id: str) -> Mapping[str, Any]:
        """This player's resolved {"weak_areas": [...], "strengths": [...]}."""
        ...


class FakePlayerInsightsSource:
    """In-process player-insights source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.insights: dict[str, Mapping[str, Any]] = {}

    def set_insights(self, person_id: str, insights: Mapping[str, Any]) -> None:
        self.insights[person_id] = insights

    async def load(self, person_id: str) -> Mapping[str, Any]:
        return self.insights.get(person_id, {"weak_areas": [], "strengths": []})


class LeaderboardOptInSource(Protocol):
    async def load(self, person_id: str) -> bool:
        """Whether this player has opted in to leaderboards; False if unrecorded."""
        ...


class FakeLeaderboardOptInSource:
    """In-process leaderboard opt-in source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.opted_in: set[str] = set()

    def set_opt_in(self, person_id: str, *, opted_in: bool) -> None:
        if opted_in:
            self.opted_in.add(person_id)
        else:
            self.opted_in.discard(person_id)

    async def load(self, person_id: str) -> bool:
        return person_id in self.opted_in
