"""Integration tests for tenant administration (M20 Step 3, FR-M20-01)."""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain import tenant_admin
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


class TestGetTenant:
    async def test_returns_none_for_unknown_tenant(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            row = await tenant_admin.get_tenant(s, uuid.uuid4())
        assert row is None

    async def test_defaults_to_active(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "adm-tenant")
        async with admin_session(session_factory) as s:
            row = await tenant_admin.get_tenant(s, tid)
        assert row is not None
        assert row["status"] == tenant_admin.ACTIVE


class TestSetTenantStatus:
    async def test_suspend_then_restore(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "adm-suspend")
        async with admin_session(session_factory) as s:
            suspended = await tenant_admin.set_tenant_status(s, tid, tenant_admin.SUSPENDED)
        assert suspended is not None
        assert suspended["status"] == tenant_admin.SUSPENDED

        async with admin_session(session_factory) as s:
            restored = await tenant_admin.set_tenant_status(s, tid, tenant_admin.ACTIVE)
        assert restored is not None
        assert restored["status"] == tenant_admin.ACTIVE

    async def test_unknown_tenant_returns_none(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as s:
            row = await tenant_admin.set_tenant_status(s, uuid.uuid4(), tenant_admin.SUSPENDED)
        assert row is None
