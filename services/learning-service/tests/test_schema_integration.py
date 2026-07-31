"""Integration tests for the M17 learning schema (Step 1).

Verifies both tables, tenant-scoped RLS (plans/evaluations are personal
data), the stage check constraint, the (tenant, person, session_ref)
idempotency constraint, the active-plan partial index, and tenant isolation.
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
LEARNING_MIGRATIONS = REPO_ROOT / "services" / "learning-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=LEARNING_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=LEARNING_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=LEARNING_MIGRATIONS)


class TestTables:
    async def test_both_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"training_plans", "plan_evaluations"} <= names

    async def test_both_tables_have_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('training_plans', 'plan_evaluations')"
                )
            )
            flags = {name: (rls, force) for name, rls, force in rows}
        assert flags["training_plans"] == (True, True)
        assert flags["plan_evaluations"] == (True, True)

    async def test_active_plan_partial_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_training_plans_active'")
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "active" in indexdef


class TestConstraints:
    async def test_invalid_stage_is_rejected(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "lrn-bad-stage")
        with pytest.raises(IntegrityError):
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO training_plans "
                        "(id, tenant_id, session_ref, stage, schema_version) "
                        "VALUES (:id, :tid, 's1', 'not_a_stage', 'plan/1.0')"
                    ),
                    {"id": uuid.uuid4(), "tid": tid},
                )


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT_PLAN = (
    "INSERT INTO training_plans (id, tenant_id, session_ref, stage, schema_version) "
    "VALUES (:id, :tid, :ref, 'cognitive', 'plan/1.0')"
)


class TestDefaults:
    async def test_fresh_plan_defaults(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "lrn-def")
        ref = f"s-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(text(_INSERT_PLAN), {"id": uuid.uuid4(), "tid": tid, "ref": ref})
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT items, targets, active FROM training_plans WHERE session_ref = :r"
                    ),
                    {"r": ref},
                )
            ).one()
        items, targets, active = row
        assert items == [] and targets == [] and active is True


class TestTenantIsolation:
    async def test_cross_tenant_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "lrn-a")
        tb = await _make_tenant(session_factory, "lrn-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT_PLAN),
                    {"id": uuid.uuid4(), "tid": tid, "ref": f"s-{uuid.uuid4().hex}"},
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM training_plans"))
            assert {r[0] for r in rows} == {ta}

    async def test_session_ref_unique_per_tenant_and_player(
        self, session_factory: async_sessionmaker
    ) -> None:
        # A real (non-NULL) person_id, deliberately -- Postgres treats NULL
        # as distinct from NULL under a plain multi-column UNIQUE
        # constraint, so a NULL person_id (as `_INSERT_PLAN` uses elsewhere)
        # would never collide and wouldn't actually exercise this constraint.
        tid = await _make_tenant(session_factory, "lrn-c")
        ref = f"s-{uuid.uuid4().hex}"
        person_id = uuid.uuid4()
        insert_with_person = (
            "INSERT INTO training_plans "
            "  (id, tenant_id, person_id, session_ref, stage, schema_version) "
            "VALUES (:id, :tid, :pid, :ref, 'cognitive', 'plan/1.0')"
        )

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(insert_with_person),
                    {"id": uuid.uuid4(), "tid": tid, "pid": person_id, "ref": ref},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()
