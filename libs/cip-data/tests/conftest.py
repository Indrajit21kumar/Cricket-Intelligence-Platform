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

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_data.engine import build_engine, build_session_factory
from cip_data.migrations import downgrade_base, upgrade_head

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url()


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Apply the base migration once at session start, roll it back at end."""
    downgrade_base(database_url)  # ensure a clean slate if a previous run crashed
    upgrade_head(database_url)
    yield database_url
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
