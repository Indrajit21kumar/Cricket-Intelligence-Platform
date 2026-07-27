"""Integration tests for the M12 knowledge schema (Step 1).

Verifies the five core tables, that they are GLOBAL (no row-level security — the
knowledge is coaching IP, access-controlled by RBAC not RLS), the fact-pattern
GIN index and the released partial index §10 calls for, and rule-version
uniqueness.
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
KNOWLEDGE_MIGRATIONS = REPO_ROOT / "services" / "knowledge-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_kg_schema() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=KNOWLEDGE_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_kg_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_kg_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestMigrationRollback:
    def test_downgrade_then_upgrade_is_clean(self, migrated_kg_schema: str) -> None:
        downgrade_base(migrated_kg_schema, migrations_dir=KNOWLEDGE_MIGRATIONS)
        upgrade_head(migrated_kg_schema, migrations_dir=KNOWLEDGE_MIGRATIONS)


class TestTables:
    async def test_all_five_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            names = {r[0] for r in rows}
        assert {"entities", "relationships", "rules", "rule_versions", "rule_conflicts"} <= names

    async def test_knowledge_tables_have_no_rls(self, engine: AsyncEngine) -> None:
        """Global coaching IP — access is RBAC + audit, not row-level security."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relname IN ('entities','relationships','rules',"
                    "'rule_versions','rule_conflicts')"
                )
            )
            rls = dict(rows)
        assert all(enabled is False for enabled in rls.values()), rls

    async def test_conditions_gin_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_rules_conditions_gin'")
            )
            assert "gin" in row.scalar_one().lower()

    async def test_released_partial_index_exists(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_rules_released'")
            )
            indexdef = row.scalar_one()
        assert "WHERE" in indexdef.upper()
        assert "released" in indexdef


class TestConstraints:
    async def test_rule_id_version_is_unique(self, session_factory: async_sessionmaker) -> None:
        async def _insert() -> None:
            async with admin_session(session_factory) as s:
                await s.execute(
                    text(
                        "INSERT INTO rules (id, rule_id, version, status) "
                        "VALUES (:id, 'KG-TEST-001', 1, 'draft')"
                    ),
                    {"id": uuid.uuid4()},
                )

        await _insert()
        with pytest.raises(IntegrityError):
            await _insert()

    async def test_rule_defaults_to_draft(self, session_factory: async_sessionmaker) -> None:
        rid = f"KG-DEF-{uuid.uuid4().hex[:8]}"
        async with admin_session(session_factory) as s:
            await s.execute(
                text("INSERT INTO rules (id, rule_id, version) VALUES (:id, :r, 1)"),
                {"id": uuid.uuid4(), "r": rid},
            )
        async with admin_session(session_factory) as s:
            status = (
                await s.execute(text("SELECT status FROM rules WHERE rule_id = :r"), {"r": rid})
            ).scalar_one()
        assert status == "draft"  # a rule is un-served until it earns a status
