"""Integration tests for the M16 dna_update_runs schema (Step 1).

Verifies the table exists, is person-anchored (NO row-level security, NO
tenant_id — mirrors M04's player_profiles, ENG-002 portability), the
(player_id, session_ref) idempotency constraint, and defaults.
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

from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
DNA_MIGRATIONS = REPO_ROOT / "services" / "dna-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=DNA_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=DNA_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=DNA_MIGRATIONS)


class TestTable:
    async def test_table_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert "dna_update_runs" in names

    async def test_has_no_rls(self, engine: AsyncEngine) -> None:
        """Person-anchored, not tenant-owned — mirrors M04's player_profiles."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'dna_update_runs'")
            )
            assert row.scalar_one() is False


_INSERT = (
    "INSERT INTO dna_update_runs (id, player_id, session_ref, model_version) "
    "VALUES (:id, :pid, :ref, 'dna-update-1.0.0')"
)


class TestDefaults:
    async def test_fresh_run_defaults(self, session_factory: async_sessionmaker) -> None:
        pid = uuid.uuid4()
        ref = f"session-{uuid.uuid4().hex}"
        async with admin_session(session_factory) as s:
            await s.execute(text(_INSERT), {"id": uuid.uuid4(), "pid": pid, "ref": ref})
        async with admin_session(session_factory) as s:
            row = (
                await s.execute(
                    text("SELECT traits_updated FROM dna_update_runs WHERE session_ref = :ref"),
                    {"ref": ref},
                )
            ).one()
        assert row[0] == {}


class TestIdempotencyConstraint:
    async def test_session_ref_unique_per_player(self, session_factory: async_sessionmaker) -> None:
        pid = uuid.uuid4()
        ref = f"session-{uuid.uuid4().hex}"

        async def _insert() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(text(_INSERT), {"id": uuid.uuid4(), "pid": pid, "ref": ref})

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_same_session_ref_allowed_for_different_players(
        self, session_factory: async_sessionmaker
    ) -> None:
        ref = f"session-{uuid.uuid4().hex}"
        async with admin_session(session_factory) as s:
            await s.execute(text(_INSERT), {"id": uuid.uuid4(), "pid": uuid.uuid4(), "ref": ref})
        async with admin_session(session_factory) as s:
            await s.execute(text(_INSERT), {"id": uuid.uuid4(), "pid": uuid.uuid4(), "ref": ref})
