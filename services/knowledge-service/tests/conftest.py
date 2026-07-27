"""Shared fixtures for knowledge-service tests.

Integration tests spin up the full app under the real lifespan — Postgres +
Redis + Kafka must be running (docker-compose up locally, service containers
+ Redpanda step in CI).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from cip_core.settings import get_settings
from cip_data.migrations import upgrade_head
from knowledge_service.main import create_app

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
# M12 authoring/review is RBAC-gated on M02-issued roles; the identity schema is
# not read directly, but the base + knowledge schemas must exist.
KNOWLEDGE_MIGRATIONS = REPO_ROOT / "services" / "knowledge-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic JWT signing key so hand-crafted access tokens verify."""
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply base + knowledge migrations once (idempotent).

    Sync fixture — must NOT be async, because ``upgrade_head`` uses
    ``asyncio.run`` internally and would collide with the pytest-asyncio
    event loop if called from an async fixture.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=KNOWLEDGE_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def integration_app(
    _migrated_database: str,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx AsyncClient bound to the fully-wired app."""
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client
