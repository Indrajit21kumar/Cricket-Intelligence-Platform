"""Integration tests for the M14 report schema (Step 1).

Verifies all three tables, their tenant-scoped RLS (reports + coach
conversations are personal data), correlation uniqueness on reports, and the
coach_messages -> coach_sessions cascade + reverse index.
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
REPORT_MIGRATIONS = REPO_ROOT / "services" / "report-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=REPORT_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_schema: str) -> None:
        downgrade_base(migrated_schema, migrations_dir=REPORT_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=REPORT_MIGRATIONS)


class TestTables:
    async def test_all_three_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"reports", "coach_sessions", "coach_messages"} <= names

    async def test_all_three_tables_have_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('reports', 'coach_sessions', 'coach_messages')"
                )
            )
            flags = {name: (rls, force) for name, rls, force in rows}
        assert flags["reports"] == (True, True)
        assert flags["coach_sessions"] == (True, True)
        assert flags["coach_messages"] == (True, True)

    async def test_coach_messages_session_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_coach_messages_session'"
                )
            )
            assert "coach_session_id" in row.scalar_one()


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT_REPORT = (
    "INSERT INTO reports (id, tenant_id, correlation_id, kg_version, schema_version) "
    "VALUES (:id, :tid, :corr, 'kg@test', 'report/1.0')"
)


class TestDefaults:
    async def test_fresh_report_defaults(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-def")
        corr = f"c-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(text(_INSERT_REPORT), {"id": uuid.uuid4(), "tid": tid, "corr": corr})
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT structure, scores, provisional FROM reports "
                        "WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        structure, scores, provisional = row
        assert structure == {} and scores == {} and provisional is False


class TestTenantIsolation:
    async def test_cross_tenant_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "acad-a")
        tb = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT_REPORT),
                    {"id": uuid.uuid4(), "tid": tid, "corr": f"c-{uuid.uuid4().hex}"},
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM reports"))
            assert {r[0] for r in rows} == {ta}

    async def test_correlation_unique_per_tenant(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-c")
        corr = f"c-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT_REPORT), {"id": uuid.uuid4(), "tid": tid, "corr": corr}
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()


class TestCoachTables:
    async def test_message_cascades_with_session(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-coach")
        person_id = uuid.uuid4()
        session_id = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO coach_sessions (id, tenant_id, person_id) VALUES (:id, :tid, :pid)"
                ),
                {"id": session_id, "tid": tid, "pid": person_id},
            )
            await s.execute(
                text(
                    "INSERT INTO coach_messages (id, tenant_id, coach_session_id, role, content) "
                    "VALUES (:id, :tid, :sid, 'user', 'why am I edging?')"
                ),
                {"id": uuid.uuid4(), "tid": tid, "sid": session_id},
            )
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(text("DELETE FROM coach_sessions WHERE id = :id"), {"id": session_id})
        async with tenant_session(session_factory, tenant_id=tid) as s:
            remaining = (
                await s.execute(
                    text("SELECT count(*) FROM coach_messages WHERE coach_session_id = :sid"),
                    {"sid": session_id},
                )
            ).scalar_one()
        assert remaining == 0
