"""Integration tests for the M13 reasoning schema (Step 1).

Verifies both tables, their tenant-scoped RLS (reasoning results are personal
data), correlation uniqueness, the reverse-lookup evidence index, and defaults.
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
REASONING_MIGRATIONS = REPO_ROOT / "services" / "reasoning-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=REASONING_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=REASONING_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=REASONING_MIGRATIONS)


class TestTables:
    async def test_both_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"reasoning_results", "finding_evidence"} <= names

    async def test_both_tables_have_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('reasoning_results', 'finding_evidence')"
                )
            )
            flags = {name: (rls, force) for name, rls, force in rows}
        assert flags["reasoning_results"] == (True, True)
        assert flags["finding_evidence"] == (True, True)

    async def test_evidence_reverse_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_finding_evidence_rule'")
            )
            indexdef = row.scalar_one()
        assert "rule_id" in indexdef and "rule_version" in indexdef


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT = (
    "INSERT INTO reasoning_results (id, tenant_id, correlation_id, kg_version, schema_version) "
    "VALUES (:id, :tid, :corr, 'kg@test', 'analysis.reasoned/1.0')"
)


class TestDefaults:
    async def test_fresh_result_defaults(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-def")
        corr = f"c-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(text(_INSERT), {"id": uuid.uuid4(), "tid": tid, "corr": corr})
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT findings, match_risk, provisional FROM reasoning_results "
                        "WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        findings, match_risk, provisional = row
        assert findings == [] and match_risk == {} and provisional is False


class TestTenantIsolation:
    async def test_cross_tenant_blocked(self, session_factory: async_sessionmaker) -> None:
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
            rows = await s.execute(text("SELECT tenant_id FROM reasoning_results"))
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
