"""Integration tests for the M15 benchmark schema (Step 1).

Verifies both tables under their DIFFERENT scoping regimes: benchmark_profiles
is GLOBAL (Book 5 reference data, no RLS — access is "released only", not
row-level security), comparisons is tenant-scoped RLS (personal data, like
M10/M11/M13/M14). Also checks the released partial index, benchmark_id+version
uniqueness, correlation uniqueness, and tenant isolation.
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
BENCHMARK_MIGRATIONS = REPO_ROOT / "services" / "benchmark-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BENCHMARK_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=BENCHMARK_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=BENCHMARK_MIGRATIONS)


class TestTables:
    async def test_both_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"benchmark_profiles", "comparisons"} <= names

    async def test_benchmark_profiles_has_no_rls(self, engine: AsyncEngine) -> None:
        """Book 5 reference data, not personal data — RBAC/released-only, not RLS."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'benchmark_profiles'")
            )
            assert row.scalar_one() is False

    async def test_comparisons_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = 'comparisons'"
                )
            )
            assert tuple(row.one()) == (True, True)

    async def test_released_partial_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_benchmark_profiles_released'"
                )
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "released" in indexdef


class TestBenchmarkProfileConstraints:
    async def test_benchmark_id_version_is_unique(
        self, session_factory: async_sessionmaker
    ) -> None:
        bid = f"BN-TEST-{uuid.uuid4().hex[:8]}"

        async def _insert() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO benchmark_profiles (id, benchmark_id, type, version) "
                        "VALUES (:id, :bid, 'skill_tier', 1)"
                    ),
                    {"id": uuid.uuid4(), "bid": bid},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_invalid_type_is_rejected(self, session_factory: async_sessionmaker) -> None:
        with pytest.raises(IntegrityError):
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO benchmark_profiles (id, benchmark_id, type, version) "
                        "VALUES (:id, 'BN-BAD', 'not_a_type', 1)"
                    ),
                    {"id": uuid.uuid4()},
                )

    async def test_profile_defaults_to_unreleased(
        self, session_factory: async_sessionmaker
    ) -> None:
        bid = f"BN-DEF-{uuid.uuid4().hex[:8]}"
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO benchmark_profiles (id, benchmark_id, type, version) "
                    "VALUES (:id, :bid, 'skill_tier', 1)"
                ),
                {"id": uuid.uuid4(), "bid": bid},
            )
        async with admin_session(session_factory) as s:
            released = (
                await s.execute(
                    text("SELECT released FROM benchmark_profiles WHERE benchmark_id = :bid"),
                    {"bid": bid},
                )
            ).scalar_one()
        assert released is False  # a profile is un-served until it earns release


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT_COMPARISON = (
    "INSERT INTO comparisons (id, tenant_id, correlation_id, benchmark_version, schema_version) "
    "VALUES (:id, :tid, :corr, 'cibl@test', 'benchmark.compared/1.0')"
)


class TestComparisonDefaults:
    async def test_fresh_comparison_defaults(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "bmk-def")
        corr = f"c-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(_INSERT_COMPARISON), {"id": uuid.uuid4(), "tid": tid, "corr": corr}
            )
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT per_metric, legend_similarity, provisional FROM comparisons "
                        "WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        per_metric, legend_similarity, provisional = row
        assert per_metric == {} and legend_similarity == {} and provisional is False


class TestTenantIsolation:
    async def test_cross_tenant_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "bmk-a")
        tb = await _make_tenant(session_factory, "bmk-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT_COMPARISON),
                    {"id": uuid.uuid4(), "tid": tid, "corr": f"c-{uuid.uuid4().hex}"},
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM comparisons"))
            assert {r[0] for r in rows} == {ta}

    async def test_correlation_unique_per_tenant(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "bmk-c")
        corr = f"c-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT_COMPARISON), {"id": uuid.uuid4(), "tid": tid, "corr": corr}
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()
