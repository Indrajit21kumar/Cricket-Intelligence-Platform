"""Shared fixtures for cip-data tests.

Integration fixtures target the local docker-compose Postgres
(``CIP_DATABASE_URL`` env or the default from docker/docker-compose.yml).
Session-scoped ``migrated_database`` runs the migration exactly once.

There is no autouse truncate — integration tests use per-test unique
tenant names (see :func:`unique_tenant_name`) so they never collide with
each other on the ``tenants.name`` UNIQUE constraint. This avoids
async-autouse fixture pitfalls with pytest-asyncio.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_data.engine import build_engine, build_session_factory
from cip_data.migrations import downgrade_base, upgrade_head

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"

# Repo layout: libs/cip-data/tests/conftest.py -> parents[3] is the repo root.
REPO_ROOT = Path(__file__).resolve().parents[3]


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


def _downgrade_all_services(url: str) -> None:
    """Downgrade every service migration project we can find, best-effort.

    Services own their own alembic projects; each one keeps foreign keys
    to the base tables (e.g. memberships.tenant_id -> tenants.id). We must
    unwind them BEFORE downgrading base, otherwise the base drop hits a
    dependent-object error.
    """
    services_dir = REPO_ROOT / "services"
    if not services_dir.is_dir():
        return
    for svc in services_dir.iterdir():
        migrations = svc / "migrations"
        if migrations.is_dir() and (migrations / "alembic.ini").exists():
            try:
                downgrade_base(url, migrations_dir=migrations)
            except Exception:  # noqa: BLE001 — best-effort cleanup
                pass


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Apply the base migration once at session start, roll it back at end.

    Also unwinds any per-service migrations that might be left over from
    a previous run (they hold FKs on the base tables and would otherwise
    block ``downgrade_base``).
    """
    _downgrade_all_services(database_url)
    downgrade_base(database_url)  # now safe — no dependents
    upgrade_head(database_url)
    yield database_url
    _downgrade_all_services(database_url)
    downgrade_base(database_url)


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    """Fresh async engine per test — safest against connection-pool state leaks."""
    eng = build_engine(migrated_database)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


@pytest.fixture
def unique_tenant_name() -> str:
    """Return a unique tenant name for the current test.

    Every integration test that inserts into ``tenants`` gets a fresh
    unique-suffixed name — avoids the ``uq_tenants_name`` UNIQUE-constraint
    collisions that would otherwise happen when the DB isn't truncated
    between tests.
    """
    return f"academy-{uuid.uuid4().hex[:8]}"
