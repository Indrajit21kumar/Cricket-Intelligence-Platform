"""Integration tests for the M18 academy schema (Step 1).

Verifies all four tables, tenant-scoped RLS (institutional data is personal
data, §12), the session-players/coach-assignments uniqueness constraints,
the status/defaults, and tenant isolation.
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
ACADEMY_MIGRATIONS = REPO_ROOT / "services" / "academy-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=ACADEMY_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=ACADEMY_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=ACADEMY_MIGRATIONS)


class TestTables:
    async def test_all_four_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {
            "academy_sessions",
            "session_players",
            "coach_assignments",
            "shared_reports",
        } <= names

    async def test_all_four_tables_have_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('academy_sessions', 'session_players', "
                    "'coach_assignments', 'shared_reports')"
                )
            )
            flags = {name: (rls, force) for name, rls, force in rows}
        assert flags["academy_sessions"] == (True, True)
        assert flags["session_players"] == (True, True)
        assert flags["coach_assignments"] == (True, True)
        assert flags["shared_reports"] == (True, True)


class TestConstraints:
    async def test_invalid_session_status_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "acad-bad-status")
        with pytest.raises(IntegrityError):
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO academy_sessions (id, tenant_id, scheduled_at, status) "
                        "VALUES (:id, :tid, now(), 'not_a_status')"
                    ),
                    {"id": uuid.uuid4(), "tid": tid},
                )

    async def test_session_defaults_to_scheduled(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-def")
        sid = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO academy_sessions (id, tenant_id, scheduled_at) "
                    "VALUES (:id, :tid, now())"
                ),
                {"id": sid, "tid": tid},
            )
        async with tenant_session(session_factory, tenant_id=tid) as s:
            status = (
                await s.execute(
                    text("SELECT status FROM academy_sessions WHERE id = :id"), {"id": sid}
                )
            ).scalar_one()
        assert status == "scheduled"

    async def test_coach_assignment_defaults_to_active(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "acad-assign")
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO coach_assignments (id, tenant_id, coach_ref, player_ref) "
                    "VALUES (:id, :tid, :coach, :player)"
                ),
                {"id": uuid.uuid4(), "tid": tid, "coach": uuid.uuid4(), "player": uuid.uuid4()},
            )
        async with tenant_session(session_factory, tenant_id=tid) as s:
            active = (await s.execute(text("SELECT active FROM coach_assignments"))).scalar_one()
        assert active is True

    async def test_duplicate_coach_player_assignment_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "acad-dup-assign")
        coach, player = uuid.uuid4(), uuid.uuid4()

        async def _insert() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO coach_assignments (id, tenant_id, coach_ref, player_ref) "
                        "VALUES (:id, :tid, :coach, :player)"
                    ),
                    {"id": uuid.uuid4(), "tid": tid, "coach": coach, "player": player},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_duplicate_session_player_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "acad-dup-session-player")
        sid = uuid.uuid4()
        player = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO academy_sessions (id, tenant_id, scheduled_at) "
                    "VALUES (:id, :tid, now())"
                ),
                {"id": sid, "tid": tid},
            )

        async def _insert() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO session_players (id, tenant_id, session_id, player_ref) "
                        "VALUES (:id, :tid, :sid, :player)"
                    ),
                    {"id": uuid.uuid4(), "tid": tid, "sid": sid, "player": player},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


class TestTenantIsolation:
    async def test_cross_tenant_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "acad-a")
        tb = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO academy_sessions (id, tenant_id, scheduled_at) "
                        "VALUES (:id, :tid, now())"
                    ),
                    {"id": uuid.uuid4(), "tid": tid},
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM academy_sessions"))
            assert {r[0] for r in rows} == {ta}
