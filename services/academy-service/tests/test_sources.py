"""Input source adapters — Fakes for dev + tests (M18 Steps 2, 4 + 5)."""

from __future__ import annotations

import asyncio
import uuid

from academy_service.domain.sources import (
    CohortContext,
    FakeActivePlanSource,
    FakeCohortContextSource,
    FakeDNATraitSource,
    FakeLeaderboardOptInSource,
    FakePlayerInsightsSource,
    FakeReportScoreSource,
    FakeRosterSource,
    RosterMember,
)
from cip_core.roles import PLAYER


class TestFakeRosterSource:
    def test_no_members_returns_empty_list(self) -> None:
        source = FakeRosterSource()
        assert asyncio.run(source.load(uuid.uuid4())) == []

    def test_set_members_is_returned_for_that_tenant_only(self) -> None:
        source = FakeRosterSource()
        tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
        members = [RosterMember(person_id=uuid.uuid4(), role=PLAYER, display_name="A")]
        source.set_members(tenant_a, members)
        assert asyncio.run(source.load(tenant_a)) == members
        assert asyncio.run(source.load(tenant_b)) == []


class TestFakeReportScoreSource:
    def test_no_scores_returns_none(self) -> None:
        source = FakeReportScoreSource()
        assert asyncio.run(source.load("player-a")) is None

    def test_set_scores_is_returned_for_that_player_only(self) -> None:
        source = FakeReportScoreSource()
        scores = {"overall": {"value": 72.0, "confidence": 0.8}}
        source.set_scores("player-a", scores)
        assert asyncio.run(source.load("player-a")) == scores
        assert asyncio.run(source.load("player-b")) is None


class TestFakeDNATraitSource:
    def test_no_traits_returns_empty_dict(self) -> None:
        source = FakeDNATraitSource()
        assert asyncio.run(source.load("player-a")) == {}

    def test_set_traits_is_returned_for_that_player_only(self) -> None:
        source = FakeDNATraitSource()
        traits = {"balance": {"value": "0.6", "confidence": 0.5}}
        source.set_traits("player-a", traits)
        assert asyncio.run(source.load("player-a")) == traits
        assert asyncio.run(source.load("player-b")) == {}


class TestFakeActivePlanSource:
    def test_no_plan_returns_none(self) -> None:
        source = FakeActivePlanSource()
        assert asyncio.run(source.load("player-a")) is None

    def test_set_plan_is_returned_for_that_player_only(self) -> None:
        source = FakeActivePlanSource()
        plan = {"stage": "foundation", "items": []}
        source.set_plan("player-a", plan)
        assert asyncio.run(source.load("player-a")) == plan
        assert asyncio.run(source.load("player-b")) is None


class TestFakeCohortContextSource:
    def test_no_context_returns_all_none(self) -> None:
        source = FakeCohortContextSource()
        assert asyncio.run(source.load("player-a")) == CohortContext()

    def test_set_context_is_returned_for_that_player_only(self) -> None:
        source = FakeCohortContextSource()
        context = CohortContext(skill_tier="intermediate", age_band="U14")
        source.set_context("player-a", context)
        assert asyncio.run(source.load("player-a")) == context
        assert asyncio.run(source.load("player-b")) == CohortContext()


class TestFakePlayerInsightsSource:
    def test_no_insights_returns_empty_lists(self) -> None:
        source = FakePlayerInsightsSource()
        assert asyncio.run(source.load("player-a")) == {"weak_areas": [], "strengths": []}

    def test_set_insights_is_returned_for_that_player_only(self) -> None:
        source = FakePlayerInsightsSource()
        insights = {"weak_areas": ["rule-1"], "strengths": ["metric-1"]}
        source.set_insights("player-a", insights)
        assert asyncio.run(source.load("player-a")) == insights
        assert asyncio.run(source.load("player-b")) == {"weak_areas": [], "strengths": []}


class TestFakeLeaderboardOptInSource:
    def test_unrecorded_player_is_not_opted_in(self) -> None:
        source = FakeLeaderboardOptInSource()
        assert asyncio.run(source.load("player-a")) is False

    def test_opted_in_player_is_returned_true(self) -> None:
        source = FakeLeaderboardOptInSource()
        source.set_opt_in("player-a", opted_in=True)
        assert asyncio.run(source.load("player-a")) is True
        assert asyncio.run(source.load("player-b")) is False

    def test_opting_out_again_reverts_to_excluded(self) -> None:
        source = FakeLeaderboardOptInSource()
        source.set_opt_in("player-a", opted_in=True)
        source.set_opt_in("player-a", opted_in=False)
        assert asyncio.run(source.load("player-a")) is False
