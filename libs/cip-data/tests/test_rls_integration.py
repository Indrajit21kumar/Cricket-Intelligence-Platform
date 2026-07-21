"""Integration tests for row-level security (AC-M01-02).

The security invariants this suite enforces are the whole point of Book 3
§4.1 / ENG-001:

1. A query on a tenant-scoped table WITHOUT a tenant context returns nothing
   (or, for INSERT, is rejected). Because ``current_setting('cip.tenant_id',
   true)`` returns NULL when unset and NULL != anything, RLS filters
   everything out.
2. A session bound to tenant A cannot read tenant B's rows.
3. A session bound to tenant A cannot INSERT a row under tenant B.
4. A same-tenant read works normally (positive control).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import CrossTenantAccess  # noqa: F401 — imported for symmetry
from cip_data.engine import admin_session, tenant_session

pytestmark = pytest.mark.integration


async def _make_tenant(session_factory: async_sessionmaker, name_prefix: str) -> uuid.UUID:
    """Insert a fresh tenant with a unique name and return its id.

    Unique names avoid uq_tenants_name collisions between integration tests
    since we don't truncate between them.
    """
    tid = uuid.uuid4()
    unique_name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, type, region) VALUES (:id, :name, 'academy', 'IN')"
            ),
            {"id": tid, "name": unique_name},
        )
    return tid


async def _add_member(
    session_factory: async_sessionmaker,
    tenant_id: uuid.UUID,
    user_ref: str,
    role: str = "player",
) -> uuid.UUID:
    """Add a row to tenant_members via a tenant-scoped session."""
    mid = uuid.uuid4()
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO tenant_members (id, tenant_id, user_ref, role) "
                "VALUES (:id, :tid, :ref, :role)"
            ),
            {"id": mid, "tid": tenant_id, "ref": user_ref, "role": role},
        )
    return mid


class TestRLSBlocksCrossTenant:
    async def test_session_a_cannot_read_tenant_b_rows(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "academy-A")
        tenant_b = await _make_tenant(session_factory, "academy-B")
        await _add_member(session_factory, tenant_a, "alice")
        await _add_member(session_factory, tenant_b, "bob")

        # Session bound to A should see only alice.
        async with tenant_session(session_factory, tenant_id=tenant_a) as session:
            rows = await session.execute(
                text("SELECT user_ref FROM tenant_members ORDER BY user_ref")
            )
            visible = [row[0] for row in rows]
        assert visible == ["alice"], f"Session for tenant A saw {visible!r} — cross-tenant leak"

    async def test_session_b_cannot_read_tenant_a_rows(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "academy-A")
        tenant_b = await _make_tenant(session_factory, "academy-B")
        await _add_member(session_factory, tenant_a, "alice")
        await _add_member(session_factory, tenant_b, "bob")

        async with tenant_session(session_factory, tenant_id=tenant_b) as session:
            rows = await session.execute(
                text("SELECT user_ref FROM tenant_members ORDER BY user_ref")
            )
            visible = [row[0] for row in rows]
        assert visible == ["bob"]

    async def test_session_a_cannot_insert_row_under_tenant_b(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "academy-A")
        tenant_b = await _make_tenant(session_factory, "academy-B")

        # Attempt to insert into tenant_members with tenant_id = B, from a
        # session bound to A. WITH CHECK on the policy blocks this.
        with pytest.raises(DBAPIError):
            async with tenant_session(session_factory, tenant_id=tenant_a) as session:
                await session.execute(
                    text(
                        "INSERT INTO tenant_members (id, tenant_id, user_ref, role) "
                        "VALUES (:id, :tid_b, 'eve', 'player')"
                    ),
                    {"id": uuid.uuid4(), "tid_b": tenant_b},
                )


class TestNoTenantContext:
    async def test_admin_session_sees_no_tenant_scoped_rows(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "academy-A")
        await _add_member(session_factory, tenant_a, "alice")

        # Admin session doesn't set cip.tenant_id — RLS filters everything.
        async with admin_session(session_factory) as session:
            rows = await session.execute(text("SELECT count(*) FROM tenant_members"))
            count = rows.scalar()
        assert count == 0, (
            "Admin session (no tenant scope) saw tenant-scoped rows — RLS not enforcing"
        )


class TestSameTenantReadWorks:
    """Positive control: RLS is not accidentally blocking legitimate reads."""

    async def test_session_reads_own_tenant_rows(self, session_factory: async_sessionmaker) -> None:
        tenant_a = await _make_tenant(session_factory, "academy-A")
        await _add_member(session_factory, tenant_a, "alice")
        await _add_member(session_factory, tenant_a, "carol")

        async with tenant_session(session_factory, tenant_id=tenant_a) as session:
            rows = await session.execute(
                text("SELECT user_ref FROM tenant_members ORDER BY user_ref")
            )
            visible = [row[0] for row in rows]
        assert visible == ["alice", "carol"]
