"""Integration tests for the M08 ball schema (Step 1) + the fake tracker.

The schema assertions that matter here are the ones encoding fail-safety:
``timing_reference`` must default to ``absolute`` and ``events`` to ``{}``, so
a run that concluded nothing says exactly that rather than implying timing it
never established.
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

from ball_service.domain.tracker import MODEL_VERSION, FakeBallTracker
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BALL_MIGRATIONS = REPO_ROOT / "services" / "ball-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_ball_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BALL_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_ball_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_ball_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestBallMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_ball_schema: str) -> None:
        downgrade_base(migrated_ball_schema, migrations_dir=BALL_MIGRATIONS)
        upgrade_head(migrated_ball_schema, migrations_dir=BALL_MIGRATIONS)


class TestTable:
    async def test_ball_runs_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "ball_runs" in {r[0] for r in rows}

    async def test_ball_runs_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'ball_runs'"
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
    "INSERT INTO ball_runs (id, tenant_id, correlation_id, model_version, quality) "
    "VALUES (:id, :tid, :corr, :mv, 'ok')"
)


class TestFailSafeDefaults:
    async def test_a_run_defaults_to_absolute_timing_and_no_events(
        self, session_factory: async_sessionmaker
    ) -> None:
        """A run must EARN release-relative timing; the default cannot promise it."""
        tid = await _make_tenant(session_factory, "acad-defaults")
        corr = f"c-{uuid.uuid4().hex}"
        async with tenant_session(session_factory, tenant_id=tid) as s:
            await s.execute(
                text(_INSERT), {"id": uuid.uuid4(), "tid": tid, "corr": corr, "mv": MODEL_VERSION}
            )
        async with tenant_session(session_factory, tenant_id=tid) as s:
            row = (
                await s.execute(
                    text(
                        "SELECT timing_reference, events, conditions_met, track_confidence "
                        "FROM ball_runs WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        timing, events, conditions_met, confidence = row
        assert timing == "absolute"
        assert events == {}  # absent events are absent keys, never zeroed frames
        assert conditions_met is False
        assert confidence == 0.0


class TestTenantIsolation:
    async def test_cross_tenant_ball_run_blocked(self, session_factory: async_sessionmaker) -> None:
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
            rows = await s.execute(text("SELECT tenant_id FROM ball_runs"))
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


class TestFakeTracker:
    def test_produces_a_plausible_delivery(self) -> None:
        frames = FakeBallTracker().detect(frame_count=20, width=1920, height=1080)
        assert len(frames) == 20
        assert all(len(f.candidates) == 1 for f in frames)
        xs = [f.candidates[0].x for f in frames]
        # The ball travels down the pitch: x increases monotonically.
        assert xs == sorted(xs)
        ys = [f.candidates[0].y for f in frames]
        # And it descends, bounces, then rises — so the lowest point is interior.
        assert ys.index(max(ys)) not in (0, len(ys) - 1)

    def test_blur_lowers_confidence_and_is_flagged(self) -> None:
        frames = FakeBallTracker(blur_from=10).detect(frame_count=20, width=1920, height=1080)
        sharp, blurred = frames[0].candidates[0], frames[15].candidates[0]
        assert sharp.streak is False and blurred.streak is True
        assert blurred.score < sharp.score

    def test_no_ball_yields_empty_frames(self) -> None:
        frames = FakeBallTracker(no_ball=True).detect(frame_count=12, width=1920, height=1080)
        assert all(f.candidates == () for f in frames)

    def test_dataset_version_is_recorded_even_when_absent(self) -> None:
        assert FakeBallTracker().dataset_version is None
        assert FakeBallTracker().version == MODEL_VERSION
