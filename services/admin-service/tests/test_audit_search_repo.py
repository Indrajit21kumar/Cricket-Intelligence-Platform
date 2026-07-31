"""Integration tests for platform-wide audit search (M20 Step 7, FR-M20-07).

Each test uses its own random ``actor`` to filter out every other test's
(and every other session's) rows in this real, shared audit_log table --
simpler than the time-window isolation Step 4/5 needed, since actor is a
precise, always-available filter here.
"""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain.audit import record_admin_action
from admin_service.domain.audit_search_repo import search_audit_log
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


class TestSearchAuditLog:
    async def test_finds_a_platform_wide_action_by_actor(
        self, session_factory: async_sessionmaker
    ) -> None:
        actor = str(uuid.uuid4())
        async with admin_session(session_factory) as s:
            await record_admin_action(
                s, admin_ref=actor, action="content.removed", target=f"clip:{uuid.uuid4()}"
            )
        async with admin_session(session_factory) as s:
            rows = await search_audit_log(s, actor=actor)
        assert len(rows) == 1
        assert rows[0]["actor"] == actor
        assert rows[0]["action"] == "admin.content.removed"

    async def test_finds_a_real_tenant_scoped_action_across_tenants(
        self, session_factory: async_sessionmaker
    ) -> None:
        """The whole point of Step 7's bypass: a REAL tenant-scoped row,
        written the way Step 2/3's tenant actions actually write it (under
        that tenant's own GUC-scoped session, per audit.py), must still be
        findable from admin-service's cross-tenant search."""
        actor = str(uuid.uuid4())
        tenant_id = await _make_tenant(session_factory, "audit-search")
        async with admin_session(session_factory) as s:
            await record_admin_action(
                s,
                admin_ref=actor,
                action="tenant.suspended",
                target=f"tenant:{tenant_id}",
                tenant_ref=tenant_id,
            )
        async with admin_session(session_factory) as s:
            rows = await search_audit_log(s, actor=actor)
        assert len(rows) == 1
        assert rows[0]["tenant_id"] == tenant_id

    async def test_filters_by_action(self, session_factory: async_sessionmaker) -> None:
        actor = str(uuid.uuid4())
        async with admin_session(session_factory) as s:
            await record_admin_action(s, admin_ref=actor, action="moderation.flagged", target="x")
            await record_admin_action(s, admin_ref=actor, action="moderation.actioned", target="x")
        async with admin_session(session_factory) as s:
            rows = await search_audit_log(s, actor=actor, action="admin.moderation.flagged")
        assert len(rows) == 1
        assert rows[0]["action"] == "admin.moderation.flagged"

    async def test_filters_by_entity(self, session_factory: async_sessionmaker) -> None:
        actor = str(uuid.uuid4())
        entity = f"case:{uuid.uuid4()}"
        async with admin_session(session_factory) as s:
            await record_admin_action(
                s, admin_ref=actor, action="moderation.flagged", target=entity
            )
            await record_admin_action(
                s, admin_ref=actor, action="moderation.flagged", target=f"case:{uuid.uuid4()}"
            )
        async with admin_session(session_factory) as s:
            rows = await search_audit_log(s, actor=actor, entity=entity)
        assert len(rows) == 1
        assert rows[0]["entity"] == entity

    async def test_no_matches_returns_empty(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as s:
            rows = await search_audit_log(s, actor=str(uuid.uuid4()))
        assert rows == []
