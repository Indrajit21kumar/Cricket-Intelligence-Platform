"""Integration tests for the M09 shot schema (Step 1) + the fake classifier.

The schema defaults are the honesty properties: a fresh row is `unclassified`
with `bat_only_fallback`, so abstention and the weaker phase method are what you
get by construction — a run must EARN a real class and standard segmentation.
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
from shot_service.domain.classifier import MODEL_VERSION, FakeShotClassifier
from shot_service.domain.features import ShotFeatures
from shot_service.domain.shot import SHOT_CLASSES, SIGNAL_BAT, SIGNAL_POSE, UNCLASSIFIED

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
SHOT_MIGRATIONS = REPO_ROOT / "services" / "shot-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_shot_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=SHOT_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_shot_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_shot_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestShotMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_shot_schema: str) -> None:
        downgrade_base(migrated_shot_schema, migrations_dir=SHOT_MIGRATIONS)
        upgrade_head(migrated_shot_schema, migrations_dir=SHOT_MIGRATIONS)


class TestTable:
    async def test_shot_runs_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            assert "shot_runs" in {r[0] for r in rows}

    async def test_shot_runs_has_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity "
                    "FROM pg_class WHERE relname = 'shot_runs'"
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
    "INSERT INTO shot_runs (id, tenant_id, correlation_id, model_version, quality) "
    "VALUES (:id, :tid, :corr, :mv, 'ok')"
)


class TestAbstentionDefaults:
    async def test_a_fresh_run_is_unclassified_with_fallback(
        self, session_factory: async_sessionmaker
    ) -> None:
        """A run must EARN a real class and standard segmentation."""
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
                        "SELECT shot_class, shot_confidence, phase_method, phase_boundaries "
                        "FROM shot_runs WHERE correlation_id = :c"
                    ),
                    {"c": corr},
                )
            ).one()
        shot_class, confidence, method, phases = row
        assert shot_class == "unclassified"
        assert confidence == 0.0
        assert method == "bat_only_fallback"
        assert phases == {}


class TestTenantIsolation:
    async def test_cross_tenant_shot_run_blocked(self, session_factory: async_sessionmaker) -> None:
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
            rows = await s.execute(text("SELECT tenant_id FROM shot_runs"))
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


def _features(**overrides: object) -> ShotFeatures:
    base: dict[str, object] = {
        "frame_count": 40,
        "signals": (SIGNAL_POSE, SIGNAL_BAT),
        "footedness": 0.8,
        "wrist_lateral_travel": 0.3,
        "swing_plane_inclination": 20.0,
    }
    base.update(overrides)
    return ShotFeatures(**base)  # type: ignore[arg-type]


class TestFakeClassifier:
    def test_returns_a_ranked_distribution_over_the_taxonomy(self) -> None:
        clf = FakeShotClassifier()
        result = clf.classify(_features())
        assert clf.version == MODEL_VERSION
        assert result.shot_class in SHOT_CLASSES
        # A full distribution, sorted, summing to ~1 — abstention needs the shape.
        assert len(result.scores) == len(SHOT_CLASSES)
        assert result.scores[0].score >= result.scores[-1].score
        assert abs(sum(s.score for s in result.scores) - 1.0) < 1e-6

    def test_pose_only_is_less_confident_than_full_fusion(self) -> None:
        """Pose alone genuinely separates fewer shots — the value says so."""
        clf = FakeShotClassifier()
        fused = clf.classify(_features(signals=(SIGNAL_POSE, SIGNAL_BAT)))
        pose_only = clf.classify(_features(signals=(SIGNAL_POSE,), swing_plane_inclination=None))
        assert pose_only.confidence < fused.confidence

    def test_dataset_version_is_recorded_even_when_absent(self) -> None:
        assert FakeShotClassifier().dataset_version is None

    def test_unclassified_is_a_real_member_not_none(self) -> None:
        assert UNCLASSIFIED == "unclassified"
        assert UNCLASSIFIED not in SHOT_CLASSES
