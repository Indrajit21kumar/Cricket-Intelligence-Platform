"""Integration tests for the M10 biomechanics schema (Step 1).

Verifies the report table, its tenant-scoped RLS, correlation uniqueness, and
the three operational indexes §12 calls for — the review-queue partial index in
particular, since it is what makes the out-of-range review workflow a small
queue rather than a full scan.
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

from biomechanics_service.domain.catalogue import (
    BM_15,
    BM_IDS,
    CATALOGUE,
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
)
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BIO_MIGRATIONS = REPO_ROOT / "services" / "biomechanics-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_bio_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BIO_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_bio_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_bio_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestBioMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_bio_schema: str) -> None:
        downgrade_base(migrated_bio_schema, migrations_dir=BIO_MIGRATIONS)
        upgrade_head(migrated_bio_schema, migrations_dir=BIO_MIGRATIONS)


class TestTable:
    async def test_reports_table_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "biomechanics_reports" in {r[0] for r in rows}

    async def test_reports_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'biomechanics_reports'"
                )
            )
            rls, force = row.one()
        assert rls is True and force is True

    async def test_review_queue_partial_index_exists(self, engine: AsyncEngine) -> None:
        """The partial index is what makes the review queue a cheap lookup."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_biomechanics_review_queue'"
                )
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "out_of_expected_range" in indexdef

    async def test_metrics_gin_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes "
                    "WHERE indexname = 'ix_biomechanics_metrics_gin'"
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
    "INSERT INTO biomechanics_reports "
    "  (id, tenant_id, correlation_id, schema_version) "
    "VALUES (:id, :tid, :corr, 'biomechanics.metrics/1.0')"
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
                        "metrics, quality FROM biomechanics_reports WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        out_of_range, reviewed, provisional, metrics, quality = row
        assert out_of_range is False
        assert reviewed is False
        assert provisional is False
        assert metrics == {} and quality == {}


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
            rows = await s.execute(text("SELECT tenant_id FROM biomechanics_reports"))
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


class TestCatalogue:
    def test_seventeen_metrics_defined(self) -> None:
        assert len(BM_IDS) == 17
        assert BM_IDS[0] == "BM-01" and BM_IDS[-1] == "BM-17"

    def test_only_bm15_is_an_estimated_proxy(self) -> None:
        """The one metric that cannot be measured from a single camera."""
        estimated = [m.id for m in CATALOGUE.values() if m.provenance == PROVENANCE_ESTIMATED]
        assert estimated == [BM_15]
        assert all(m.provenance == PROVENANCE_MEASURED for m in CATALOGUE.values() if m.id != BM_15)
