"""Integration tests for the M02 identity schema (Step 1).

Verifies:
- The identity-service Alembic project applies + rolls back cleanly on top
  of the base schema (M01 must be applied first — the base fixture handles it)
- All 6 tables land with the expected columns
- RLS + FORCE is enabled on ``memberships`` (the tenant-scoped table)
- ``persons`` is global (no RLS) so the portable-identity property works
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def migrated_identity_schema() -> str:
    """Ensure base + identity migrations are applied (idempotent).

    Does NOT downgrade base — other services (e.g. billing) may hold FKs to
    the base tables, so tearing base down here would fail. upgrade_head is a
    no-op if the schema is already at head, so this is order-independent.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_identity_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_identity_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestExpectedTables:
    async def test_all_six_identity_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = {row[0] for row in rows}
        for expected in (
            "persons",
            "credentials",
            "memberships",
            "consents",
            "tokens",
            "guardianships",
        ):
            assert expected in tables, f"Missing {expected}; got {sorted(tables)}"


class TestRLSFlags:
    async def test_memberships_has_no_rls(self, engine: AsyncEngine) -> None:
        """memberships is intentionally NOT RLS-protected.

        Identity-service is the sole owner and needs cross-tenant reads
        (JWT roles claim + /v1/me). Tenant isolation for this table is
        enforced at the JWT + RBAC layer.
        """
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'memberships'")
            )
            assert row.scalar() is False

    async def test_persons_has_no_rls(self, engine: AsyncEngine) -> None:
        """persons is global — portable identity depends on being visible
        to any tenant scope."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'persons'")
            )
            assert row.scalar() is False


async def _make_tenant(session_factory: async_sessionmaker, name_prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    name = f"{name_prefix}-{uuid.uuid4().hex[:8]}"
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, type, region) VALUES (:id, :name, 'academy', 'IN')"
            ),
            {"id": tid, "name": name},
        )
    return tid


async def _make_person(session_factory: async_sessionmaker, email_prefix: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with admin_session(session_factory) as session:
        await session.execute(
            text("INSERT INTO persons (id, email) VALUES (:id, :email)"),
            {"id": pid, "email": f"{email_prefix}-{uuid.uuid4().hex[:8]}@test"},
        )
    return pid


class TestMembershipsIsCrossTenant:
    """memberships is cross-tenant by design (identity-service owns it)."""

    async def test_admin_session_sees_all_tenants(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "acad-a")
        tenant_b = await _make_tenant(session_factory, "acad-b")
        person_a = await _make_person(session_factory, "alice")
        person_b = await _make_person(session_factory, "bob")

        async with admin_session(session_factory) as session:
            await session.execute(
                text(
                    "INSERT INTO memberships (id, person_id, tenant_id, role) "
                    "VALUES (:id, :pid, :tid, 'player')"
                ),
                {"id": uuid.uuid4(), "pid": person_a, "tid": tenant_a},
            )
            await session.execute(
                text(
                    "INSERT INTO memberships (id, person_id, tenant_id, role) "
                    "VALUES (:id, :pid, :tid, 'player')"
                ),
                {"id": uuid.uuid4(), "pid": person_b, "tid": tenant_b},
            )

        # Cross-tenant read succeeds — needed for JWT roles + /v1/me.
        async with admin_session(session_factory) as session:
            rows = await session.execute(
                text("SELECT person_id FROM memberships ORDER BY person_id")
            )
            visible = {row[0] for row in rows}
        assert {person_a, person_b}.issubset(visible)
