"""Input source adapters — Fakes for dev + tests (M18 Steps 2 + 4)."""

from __future__ import annotations

import asyncio
import uuid

from academy_service.domain.sources import (
    FakeActivePlanSource,
    FakeDNATraitSource,
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
