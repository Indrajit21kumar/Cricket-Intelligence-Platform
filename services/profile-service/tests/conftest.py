"""Shared fixtures for profile-service tests.

Integration tests spin up the full app under the real lifespan — Postgres +
Redis + Kafka must be running (docker-compose up locally, service containers
+ Redpanda step in CI).

The profile-service reads M02 tables (consents, memberships, guardianships,
persons) for the shared cip-core consent check, so the migrated DB applies
base + identity + profile migrations.
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
from profile_service.main import create_app

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"
PROFILE_MIGRATIONS = REPO_ROOT / "services" / "profile-service" / "migrations"


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
    """Apply base + identity + profile migrations once for the session.

    Sync fixture — ``upgrade_head`` uses ``asyncio.run`` internally, which
    would collide with the pytest-asyncio event loop if called from async.
    Order-independent + idempotent (never downgrades base).
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    upgrade_head(url, migrations_dir=PROFILE_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def integration_app(
    _migrated_database: str,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx AsyncClient bound to the fully-wired app under lifespan."""
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client
