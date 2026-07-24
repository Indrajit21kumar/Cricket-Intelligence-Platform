"""Integration tests for the M07 bat schema (Step 1) + the fake detector.

Verifies:
- bat_runs exists, is tenant-scoped with RLS + FORCE.
- correlation_id is unique per (tenant, clip) — the idempotency anchor.
- Cross-tenant reads are blocked by RLS.
- Migration rolls back + re-applies cleanly (bat-only; never base).
- The fake detector emits the three detected bat parts and honours its seams.
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

from bat_service.domain.bat import DETECTED_PARTS
from bat_service.domain.detector import MODEL_VERSION, FakeBatDetector
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BAT_MIGRATIONS = REPO_ROOT / "services" / "bat-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_bat_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BAT_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_bat_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_bat_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestBatMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_bat_schema: str) -> None:
        downgrade_base(migrated_bat_schema, migrations_dir=BAT_MIGRATIONS)
        upgrade_head(migrated_bat_schema, migrations_dir=BAT_MIGRATIONS)


class TestTable:
    async def test_bat_runs_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "bat_runs" in {r[0] for r in rows}

    async def test_bat_runs_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'bat_runs'"
                )
            )
            rls, force = row.one()
        assert rls is True and force is True


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


_INSERT = (
    "INSERT INTO bat_runs (id, tenant_id, correlation_id, model_version, quality) "
    "VALUES (:id, :tid, :corr, :mv, 'ok')"
)


class TestTenantIsolation:
    async def test_cross_tenant_bat_run_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "acad-a")
        tb = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT),
                    {
                        "id": uuid.uuid4(),
                        "tid": tid,
                        "corr": f"c-{uuid.uuid4().hex}",
                        "mv": MODEL_VERSION,
                    },
                )

        await _add(ta)
        await _add(tb)
        async with tenant_session(session_factory, tenant_id=ta) as s:
            rows = await s.execute(text("SELECT tenant_id FROM bat_runs"))
            assert {r[0] for r in rows} == {ta}

    async def test_correlation_unique_per_tenant(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-c")
        corr = f"c-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(_INSERT),
                    {"id": uuid.uuid4(), "tid": tid, "corr": corr, "mv": MODEL_VERSION},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()


class TestFakeDetector:
    def test_emits_detected_parts_per_frame(self) -> None:
        det = FakeBatDetector()
        frames = det.detect(frame_count=12, width=1920, height=1080)
        assert len(frames) == 12
        assert det.version == MODEL_VERSION
        for fr in frames:
            assert len(fr.bats) == 1
            parts = [p.part for p in fr.bats[0].parts]
            # Only the three DETECTED parts here — sweet_spot is derived later.
            assert parts == list(DETECTED_PARTS)
            for p in fr.bats[0].parts:
                assert 0.0 <= p.confidence <= 1.0

    def test_failed_frames_yield_no_detection(self) -> None:
        det = FakeBatDetector(fail_frames=frozenset({2, 5}))
        frames = det.detect(frame_count=8, width=1920, height=1080)
        assert frames[2].bats == () and frames[5].bats == ()
        assert all(frames[i].bats for i in (0, 1, 3, 4, 6, 7))

    def test_decoy_adds_a_second_bat(self) -> None:
        det = FakeBatDetector(decoy=True)
        frames = det.detect(frame_count=4, width=1920, height=1080)
        assert all(len(fr.bats) == 2 for fr in frames)

    def test_dataset_version_is_recorded_even_when_absent(self) -> None:
        """A detector with no labelled corpus says so rather than implying one."""
        assert FakeBatDetector().dataset_version is None
