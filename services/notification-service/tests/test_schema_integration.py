"""Integration tests for the M19 notification schema (Step 1).

Verifies all three tables exist, are person-anchored with NO row-level
security (§9's own column lists never name tenant_id — see the migration
docstring), the idempotency/uniqueness constraints, defaults, and the
delivery_attempts -> notifications cascade.
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
NOTIFICATION_MIGRATIONS = REPO_ROOT / "services" / "notification-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=NOTIFICATION_MIGRATIONS)
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
        downgrade_base(migrated_schema, migrations_dir=NOTIFICATION_MIGRATIONS)
        upgrade_head(migrated_schema, migrations_dir=NOTIFICATION_MIGRATIONS)


class TestTables:
    async def test_all_three_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"notifications", "preferences", "delivery_attempts"} <= names

    async def test_none_of_the_three_tables_have_rls(self, engine: AsyncEngine) -> None:
        """Person-anchored, no tenant_id — access control is app-layer, not RLS."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relname IN ('notifications', 'preferences', 'delivery_attempts')"
                )
            )
            flags = dict(rows.all())
        assert flags["notifications"] is False
        assert flags["preferences"] is False
        assert flags["delivery_attempts"] is False


class TestConstraints:
    async def test_invalid_channel_is_rejected(self, session_factory: async_sessionmaker) -> None:
        with pytest.raises(IntegrityError):
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO notifications "
                        "  (id, recipient_ref, type, channel, event_ref, idempotency_key) "
                        "VALUES (:id, :rec, 'report.ready', 'carrier_pigeon', 'evt-1', :key)"
                    ),
                    {"id": uuid.uuid4(), "rec": uuid.uuid4(), "key": f"k-{uuid.uuid4()}"},
                )

    async def test_notification_defaults_to_pending(
        self, session_factory: async_sessionmaker
    ) -> None:
        nid = uuid.uuid4()
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO notifications "
                    "  (id, recipient_ref, type, channel, event_ref, idempotency_key) "
                    "VALUES (:id, :rec, 'report.ready', 'email', 'evt-2', :key)"
                ),
                {"id": nid, "rec": uuid.uuid4(), "key": f"k-{uuid.uuid4()}"},
            )
        async with admin_session(session_factory) as s:
            status = (
                await s.execute(
                    text("SELECT status FROM notifications WHERE id = :id"), {"id": nid}
                )
            ).scalar_one()
        assert status == "pending"

    async def test_duplicate_idempotency_key_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        key = f"k-{uuid.uuid4()}"

        async def _insert() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO notifications "
                        "  (id, recipient_ref, type, channel, event_ref, idempotency_key) "
                        "VALUES (:id, :rec, 'report.ready', 'email', 'evt-3', :key)"
                    ),
                    {"id": uuid.uuid4(), "rec": uuid.uuid4(), "key": key},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_preference_defaults_to_enabled(
        self, session_factory: async_sessionmaker
    ) -> None:
        pid = uuid.uuid4()
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO preferences (id, person_ref, channel, topic) "
                    "VALUES (:id, :person, 'email', 'report_ready')"
                ),
                {"id": pid, "person": uuid.uuid4()},
            )
        async with admin_session(session_factory) as s:
            enabled = (
                await s.execute(text("SELECT enabled FROM preferences WHERE id = :id"), {"id": pid})
            ).scalar_one()
        assert enabled is True

    async def test_duplicate_preference_pair_is_rejected(
        self, session_factory: async_sessionmaker
    ) -> None:
        person = uuid.uuid4()

        async def _insert() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO preferences (id, person_ref, channel, topic) "
                        "VALUES (:id, :person, 'push', 'plan_updated')"
                    ),
                    {"id": uuid.uuid4(), "person": person},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_delivery_attempt_cascades_on_notification_delete(
        self, session_factory: async_sessionmaker
    ) -> None:
        nid = uuid.uuid4()
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO notifications "
                    "  (id, recipient_ref, type, channel, event_ref, idempotency_key) "
                    "VALUES (:id, :rec, 'report.ready', 'email', 'evt-4', :key)"
                ),
                {"id": nid, "rec": uuid.uuid4(), "key": f"k-{uuid.uuid4()}"},
            )
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "INSERT INTO delivery_attempts (id, notification_id, attempt, status) "
                    "VALUES (:id, :nid, 1, 'success')"
                ),
                {"id": uuid.uuid4(), "nid": nid},
            )
        async with admin_session(session_factory) as s:
            await s.execute(text("DELETE FROM notifications WHERE id = :id"), {"id": nid})
        async with admin_session(session_factory) as s:
            remaining = (
                await s.execute(
                    text("SELECT count(*) FROM delivery_attempts WHERE notification_id = :nid"),
                    {"nid": nid},
                )
            ).scalar_one()
        assert remaining == 0
