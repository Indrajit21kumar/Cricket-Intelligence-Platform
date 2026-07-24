"""Integration tests for the M06 pose schema (Step 1) + the fake pose model.

Verifies:
- pose_runs exists, is tenant-scoped with RLS + FORCE.
- correlation_id is unique per (tenant, clip) — the idempotency anchor.
- Cross-tenant reads are blocked by RLS.
- Migration rolls back + re-applies cleanly (pose-only; never base).
- The fake pose model emits the 17 canonical joints per person per frame.
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
from pose_service.domain.keypoints import CANONICAL_JOINTS
from pose_service.domain.model import MODEL_VERSION, FakePoseModel

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
POSE_MIGRATIONS = REPO_ROOT / "services" / "pose-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_pose_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=POSE_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_pose_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_pose_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestPoseMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_pose_schema: str) -> None:
        downgrade_base(migrated_pose_schema, migrations_dir=POSE_MIGRATIONS)
        upgrade_head(migrated_pose_schema, migrations_dir=POSE_MIGRATIONS)


class TestTable:
    async def test_pose_runs_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "pose_runs" in {r[0] for r in rows}

    async def test_pose_runs_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'pose_runs'"
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


class TestTenantIsolation:
    async def test_cross_tenant_pose_run_blocked(self, session_factory: async_sessionmaker) -> None:
        ta = await _make_tenant(session_factory, "acad-a")
        tb = await _make_tenant(session_factory, "acad-b")

        async def _add(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO pose_runs "
                        "  (id, tenant_id, correlation_id, model_version, subject_status, quality) "
                        "VALUES (:id, :tid, :corr, :mv, 'tracked', 'ok')"
                    ),
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
            rows = await s.execute(text("SELECT tenant_id FROM pose_runs"))
            assert {r[0] for r in rows} == {ta}

    async def test_correlation_unique_per_tenant(self, session_factory: async_sessionmaker) -> None:
        tid = await _make_tenant(session_factory, "acad-c")
        corr = f"c-{uuid.uuid4().hex}"

        async def _add() -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO pose_runs "
                        "  (id, tenant_id, correlation_id, model_version, subject_status, quality) "
                        "VALUES (:id, :tid, :corr, :mv, 'tracked', 'ok')"
                    ),
                    {"id": uuid.uuid4(), "tid": tid, "corr": corr, "mv": MODEL_VERSION},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()


class TestFakeModel:
    def test_emits_canonical_joints_per_person(self) -> None:
        model = FakePoseModel()
        frames = model.infer(frame_count=10, width=1920, height=1080)
        assert len(frames) == 10
        assert model.version == MODEL_VERSION
        for fr in frames:
            assert len(fr.persons) == 1
            joints = [k.joint for k in fr.persons[0].keypoints]
            assert joints == list(CANONICAL_JOINTS)
            assert all(0.0 <= k.confidence <= 1.0 for k in fr.persons[0].keypoints)

    def test_patch_produces_multiple_subjects(self) -> None:
        model = FakePoseModel()
        model.patch(persons=3)
        frames = model.infer(frame_count=3, width=1280, height=720)
        assert all(len(f.persons) == 3 for f in frames)
        # The primary (person 0) is the largest — tracking will prefer it.
        for f in frames:
            assert f.persons[0].area >= max(p.area for p in f.persons)
