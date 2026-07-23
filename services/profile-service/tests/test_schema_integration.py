"""Integration tests for the M04 player-profile schema (Step 1).

Verifies:
- All 6 tables land with the expected columns.
- Tables are person-anchored globals: NO row-level security, NO tenant_id
  (ENG-002 portability — access control is the app-layer consent helper).
- ``player_profiles.person_id`` is a plain UUID with NO cross-service FK
  (service-boundary hygiene) but IS UNIQUE (1:1 with a person).
- Trait tables carry provenance + confidence (Trust Doctrine).
- The migration rolls back + re-applies cleanly (billing-only style: this
  project never touches the shared base).
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
PROFILE_MIGRATIONS = REPO_ROOT / "services" / "profile-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def migrated_profile_schema() -> str:
    """Ensure base + profile migrations are applied (idempotent).

    Does NOT downgrade base — other services hold rows/roles under it.
    Profile-only rollback is exercised in TestProfileMigrationRollback.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=PROFILE_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_profile_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_profile_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestProfileMigrationRollback:
    """Profile migration rolls back + re-applies cleanly (Step 1 Done-when).

    Profile-only: drops profile tables, re-applies them. Never touches base.
    """

    def test_downgrade_then_upgrade_is_clean(self, migrated_profile_schema: str) -> None:
        downgrade_base(migrated_profile_schema, migrations_dir=PROFILE_MIGRATIONS)
        upgrade_head(migrated_profile_schema, migrations_dir=PROFILE_MIGRATIONS)


class TestTables:
    async def test_all_profile_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = {r[0] for r in rows}
        for expected in (
            "player_profiles",
            "dna_traits",
            "dna_trait_history",
            "dna_snapshots",
            "history_index",
            "personal_baselines",
        ):
            assert expected in tables, f"missing {expected}; got {sorted(tables)}"


class TestPersonAnchoredNoRLS:
    @pytest.mark.parametrize(
        "table",
        [
            "player_profiles",
            "dna_traits",
            "dna_trait_history",
            "dna_snapshots",
            "history_index",
            "personal_baselines",
        ],
    )
    async def test_no_row_level_security(self, engine: AsyncEngine, table: str) -> None:
        """Person-anchored tables must NOT have RLS (ENG-002 portability)."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = :name"),
                {"name": table},
            )
            assert row.scalar() is False

    @pytest.mark.parametrize(
        "table",
        [
            "player_profiles",
            "dna_traits",
            "dna_trait_history",
            "dna_snapshots",
            "history_index",
            "personal_baselines",
        ],
    )
    async def test_no_tenant_id_column(self, engine: AsyncEngine, table: str) -> None:
        """No tenant_id anywhere — the profile belongs to a person, not a tenant."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
            cols = {r[0] for r in rows}
        assert "tenant_id" not in cols


class TestPersonIdIsUnconstrainedButUnique:
    async def test_person_id_has_no_foreign_key(self, engine: AsyncEngine) -> None:
        """person_id must NOT FK to persons (cross-service boundary)."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tc.constraint_type "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.key_column_usage kcu "
                    "  ON tc.constraint_name = kcu.constraint_name "
                    "WHERE tc.table_name = 'player_profiles' "
                    "  AND kcu.column_name = 'person_id'"
                )
            )
            types = {r[0] for r in rows}
        assert "FOREIGN KEY" not in types
        # But it IS unique (1:1 with a person).
        assert "UNIQUE" in types

    async def test_one_profile_per_person(self, session_factory: async_sessionmaker) -> None:
        person_id = uuid.uuid4()
        async with admin_session(session_factory) as s:
            await s.execute(
                text("INSERT INTO player_profiles (id, person_id) VALUES (:id, :p)"),
                {"id": uuid.uuid4(), "p": person_id},
            )
        # A second profile for the same person violates the UNIQUE constraint.
        with pytest.raises(IntegrityError):  # asyncpg UniqueViolation surfaced by SQLAlchemy
            async with admin_session(session_factory) as s:
                await s.execute(
                    text("INSERT INTO player_profiles (id, person_id) VALUES (:id, :p)"),
                    {"id": uuid.uuid4(), "p": person_id},
                )


class TestTraitProvenance:
    async def test_dna_traits_have_provenance_and_confidence(self, engine: AsyncEngine) -> None:
        """Trust Doctrine: computed trait values carry provenance + confidence."""
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'dna_traits'"
                )
            )
            cols = {r[0] for r in rows}
        assert "provenance" in cols
        assert "confidence" in cols

    async def test_history_carries_provenance(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'dna_trait_history'"
                )
            )
            cols = {r[0] for r in rows}
        assert "provenance" in cols
        assert "snapshot_at" in cols
