"""Integration tests for the M11 physics schema (Step 1).

Verifies the report table, its tenant-scoped RLS, correlation uniqueness, and
the operational indexes §11 calls for — the review-queue partial index in
particular (so the out-of-range review workflow is a small queue, not a full
scan) and the GIN index over ``quantities`` (so M15/M12 can query by physics
value). Also asserts the two auditability columns the trust doctrine requires:
``schema_version`` (wire contract) and ``model_version`` (estimation model).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
PHY_MIGRATIONS = REPO_ROOT / "services" / "physics-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_phy_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=PHY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_phy_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_phy_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestPhyMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_phy_schema: str) -> None:
        downgrade_base(migrated_phy_schema, migrations_dir=PHY_MIGRATIONS)
        upgrade_head(migrated_phy_schema, migrations_dir=PHY_MIGRATIONS)


class TestTable:
    async def test_reports_table_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "physics_reports" in {r[0] for r in rows}

    async def test_reports_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'physics_reports'"
                )
            )
            rls, force = row.one()
        assert rls is True and force is True

    async def test_review_queue_partial_index_exists(self, engine: AsyncEngine) -> None:
        """The partial index is what makes the review queue a cheap lookup."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_physics_review_queue'")
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "out_of_expected_range" in indexdef

    async def test_quantities_gin_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_physics_quantities_gin'"
                )
            )
            assert "gin" in row.scalar_one().lower()


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT = (
    "INSERT INTO physics_reports "
    "  (id, tenant_id, correlation_id, schema_version, model_version) "
    "VALUES (:id, :tid, :corr, 'physics.metrics/1.0', 'phys-est-2026.07')"
)


class TestDefaults:
    async def test_a_fresh_report_is_in_range_and_not_provisional(
        self, session_factory: async_sessionmaker
    ) -> None:
        """A report is trustworthy unless the compute actively says otherwise."""
        tid = await _make_tenant(session_factory, "acad-defaults")
        corr = f"c-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(text(_INSERT), {"id": uuid.uuid4(), "tid": tid, "corr": corr})
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT out_of_expected_range, reviewed_by_human, provisional, "
                        "quantities, kinetic_chain, quality FROM physics_reports "
                        "WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        out_of_range, reviewed, provisional, quantities, kinetic_chain, quality = row
        assert out_of_range is False
        assert reviewed is False
        assert provisional is False
        assert quantities == {} and kinetic_chain == {} and quality == {}


class TestTenantIsolation:
    async def test_cross_tenant_report_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "acad-a")
        tb = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT), {"id": uuid.uuid4(), "tid": tid, "corr": f"c-{uuid.uuid4().hex}"}
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM physics_reports"))
            assert {r[0] for r in rows} == {ta}

    async def test_correlation_unique_per_tenant(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-c")
        corr = f"c-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(text(_INSERT), {"id": uuid.uuid4(), "tid": tid, "corr": corr})

        await _add()
        with pytest.raises(IntegrityError):
            await _add()
