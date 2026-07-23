"""Integration tests for the M05 video-intelligence schema (Step 1).

Verifies:
- All 4 tables land.
- Every table is tenant-scoped with RLS + FORCE (NFR-M05-04).
- correlation_id is unique per (tenant, clip) — the idempotency anchor.
- Cross-tenant reads are blocked by RLS.
- The migration rolls back + re-applies cleanly (video-only; never base).
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
VIDEO_MIGRATIONS = REPO_ROOT / "services" / "video-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def migrated_video_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=VIDEO_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_video_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_video_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestVideoMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_video_schema: str) -> None:
        downgrade_base(migrated_video_schema, migrations_dir=VIDEO_MIGRATIONS)
        upgrade_head(migrated_video_schema, migrations_dir=VIDEO_MIGRATIONS)


class TestTables:
    async def test_all_video_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = {r[0] for r in rows}
        for expected in ("ingestions", "processing_results", "calibrations", "quality_flags"):
            assert expected in tables, f"missing {expected}; got {sorted(tables)}"


class TestRLSFlags:
    @pytest.mark.parametrize(
        "table", ["ingestions", "processing_results", "calibrations", "quality_flags"]
    )
    async def test_tenant_scoped_tables_have_rls(self, engine: AsyncEngine, table: str) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :name"
                ),
                {"name": table},
            )
            rls, force = row.one()
        assert rls is True and force is True


async def _make_tenant(session_factory: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(session_factory) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


class TestTenantIsolation:
    async def test_cross_tenant_ingestion_blocked(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "acad-a")
        tenant_b = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO ingestions "
                        "  (id, tenant_id, person_id, correlation_id, source_type) "
                        "VALUES (:id, :tid, :pid, :corr, 'mobile')"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": tid,
                        "pid": uuid.uuid4(),
                        "corr": f"corr-{uuid.uuid4().hex}",
                    },
                )

        await _add(tenant_a)
        await _add(tenant_b)

        async with tenant_session(session_factory, tenant_id=tenant_a) as s:
            rows = await s.execute(text("SELECT tenant_id FROM ingestions"))
            visible = {r[0] for r in rows}
        assert visible == {tenant_a}

    async def test_correlation_id_unique_per_tenant(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "acad-c")
        corr = f"corr-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO ingestions "
                        "  (id, tenant_id, person_id, correlation_id, source_type) "
                        "VALUES (:id, :tid, :pid, :corr, 'mobile')"
                    ),
                    {"id": uuid.uuid4(), "tid": tid, "pid": uuid.uuid4(), "corr": corr},
                )

        await _add()
        with pytest.raises(IntegrityError):  # UniqueViolation on (tenant_id, correlation_id)
            await _add()
