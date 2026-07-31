"""Integration tests for the M20 admin ops + warehouse schema (Step 1).

Verifies the three ops tables (global, no RLS — RBAC-governed instead, same
pattern M12 established), the review-queue/moderation partial indexes, the
separate ``warehouse`` schema and its fact/dimension tables, and the
dedupe-key uniqueness that makes warehouse ingestion idempotent.
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
ADMIN_MIGRATIONS = REPO_ROOT / "services" / "admin-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=ADMIN_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=ADMIN_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=ADMIN_MIGRATIONS)


class TestOpsTables:
    async def test_all_three_ops_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"moderation_cases", "review_queue", "admin_actions"} <= names

    async def test_ops_tables_have_no_rls(self, engine: AsyncEngine) -> None:
        """Platform-global, RBAC-governed — same pattern as M12's knowledge tables."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relname IN ('moderation_cases', 'review_queue', 'admin_actions')"
                )
            )
            rls = dict(rows.all())
        assert all(enabled is False for enabled in rls.values()), rls

    async def test_review_queue_pending_partial_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_review_queue_pending'")
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "pending" in indexdef

    async def test_moderation_open_partial_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_moderation_cases_open'")
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "open" in indexdef


class TestOpsConstraints:
    async def test_review_queue_unique_per_tenant_and_stroke(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = uuid.uuid4()
        ref = f"m10-{uuid.uuid4().hex[:10]}"

        async def _add() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO review_queue (id, tenant_id, stroke_ref, reason) "
                        "VALUES (:id, :tid, :ref, 'elbow_flexion_at_impact out of range')"
                    ),
                    {"id": uuid.uuid4(), "tid": tid, "ref": ref},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()

    async def test_invalid_moderation_status_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        with pytest.raises(IntegrityError):
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO moderation_cases (id, subject_ref, reason, status) "
                        "VALUES (:id, 'video:abc', 'flagged', 'not_a_status')"
                    ),
                    {"id": uuid.uuid4()},
                )

    async def test_review_queue_defaults_to_pending(
        self, session_factory: async_sessionmaker
    ) -> None:
        tid = uuid.uuid4()
        ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO review_queue (id, tenant_id, stroke_ref, reason) "
                    "VALUES (:id, :tid, :ref, 'bat_speed out of range')"
                ),
                {"id": uuid.uuid4(), "tid": tid, "ref": ref},
            )
        async with admin_session(session_factory) as s:
            status = (
                await s.execute(
                    text("SELECT status FROM review_queue WHERE stroke_ref = :ref"), {"ref": ref}
                )
            ).scalar_one()
        assert status == "pending"


class TestWarehouseSchema:
    async def test_warehouse_schema_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT schema_name FROM information_schema.schemata "
                    "WHERE schema_name = 'warehouse'"
                )
            )
            assert row.scalar_one() == "warehouse"

    async def test_warehouse_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'warehouse'")
            )
            names = {r[0] for r in rows}
        assert {"fact_usage_event", "fact_revenue_event", "dim_date"} <= names

    async def test_warehouse_tables_are_separate_from_public_schema(
        self, engine: AsyncEngine
    ) -> None:
        """NFR-M20-03: the warehouse's own tables never collide with prod tables."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            public_names = {r[0] for r in rows}
        assert "fact_usage_event" not in public_names
        assert "fact_revenue_event" not in public_names


class TestWarehouseConstraints:
    async def test_fact_usage_event_dedupe_key_is_unique(
        self, session_factory: async_sessionmaker
    ) -> None:
        dedupe = f"video.normalized:{uuid.uuid4().hex}"

        async def _add() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO warehouse.fact_usage_event "
                        "  (id, event_topic, tenant_id, correlation_id, occurred_at, dedupe_key) "
                        "VALUES (:id, 'video.normalized', :tid, :corr, now(), :dedupe)"
                    ),
                    {"id": uuid.uuid4(), "tid": uuid.uuid4(), "corr": "c1", "dedupe": dedupe},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()

    async def test_fact_revenue_event_dedupe_key_is_unique(
        self, session_factory: async_sessionmaker
    ) -> None:
        dedupe = f"invoice.paid:{uuid.uuid4().hex}"

        async def _add() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO warehouse.fact_revenue_event "
                        "  (id, event_topic, tenant_id, occurred_at, dedupe_key) "
                        "VALUES (:id, 'billing.invoice.paid', :tid, now(), :dedupe)"
                    ),
                    {"id": uuid.uuid4(), "tid": uuid.uuid4(), "dedupe": dedupe},
                )

        await _add()
        with pytest.raises(IntegrityError):
            await _add()

    async def test_dim_date_upsert_is_idempotent(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO warehouse.dim_date (date, year, month, day, iso_week, iso_dow) "
                    "VALUES ('2026-07-31', 2026, 7, 31, 31, 5) "
                    "ON CONFLICT (date) DO NOTHING"
                )
            )
        async with admin_session(session_factory) as s:
            # Re-insert the same date — must not raise.
            await s.execute(
                text(
                    "INSERT INTO warehouse.dim_date (date, year, month, day, iso_week, iso_dow) "
                    "VALUES ('2026-07-31', 2026, 7, 31, 31, 5) "
                    "ON CONFLICT (date) DO NOTHING"
                )
            )
