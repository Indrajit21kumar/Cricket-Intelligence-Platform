"""Shared fixtures for video-service tests.

Integration tests spin up the full app under the real lifespan — Postgres +
Redis + Kafka must be running (docker-compose up locally, service containers
+ Redpanda step in CI).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head
from video_service.main import create_app

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
VIDEO_MIGRATIONS = REPO_ROOT / "services" / "video-service" / "migrations"


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
    """Apply base + video migrations once for the session (idempotent).

    Sync fixture — ``upgrade_head`` uses ``asyncio.run`` internally, which
    would collide with the pytest-asyncio loop if called from async.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=VIDEO_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def integration_app(
    _migrated_database: str,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx AsyncClient bound to the fully-wired app.

    The lifespan runs, so DB engine + event bus + Redis are actually started
    and stopped around the test. Uses env-provided URLs (from the CI
    integration job or the local docker-compose).
    """
    app = create_app()
    # raise_app_exceptions=False lets the app's exception handler produce a
    # 500 envelope we can inspect (matches real HTTP behaviour). Without it,
    # httpx re-raises unhandled exceptions to the test as if the app crashed.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest_asyncio.fixture
async def tenant_id(_migrated_database: str) -> uuid.UUID:
    """Create a fresh tenant in Postgres and return its id.

    Kept per-test (not session-scoped) so each test has its own isolation
    space + a stable tenant to bind requests to.
    """
    engine = build_engine(_migrated_database)
    session_factory = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(session_factory) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) "
                    "VALUES (:id, :name, 'academy', 'IN')"
                ),
                {"id": tid, "name": f"ref-svc-{uuid.uuid4().hex[:8]}"},
            )
        yield tid
    finally:
        await engine.dispose()
