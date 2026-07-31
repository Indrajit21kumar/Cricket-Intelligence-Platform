"""Input source adapters — Fakes for dev + tests (M18 Step 2)."""

from __future__ import annotations

import asyncio
import uuid

from academy_service.domain.sources import FakeRosterSource, RosterMember
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
