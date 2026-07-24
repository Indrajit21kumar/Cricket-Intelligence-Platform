"""Shared fixtures for ball-service tests.

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

from ball_service.main import create_app
from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
# M08's annotation consent gate reads M02-owned tables (persons, consents, guardianships),
# so the identity schema must exist for the annotation pipeline to be testable.
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"
# The annotation_queue tables are owned by bat-service's Alembic project (M07
# created them) and SHARED with M08 through cip-annotation, so M08's test
# database needs M07's schema. Applying it explicitly rather than relying on
# whatever another service's test run happened to leave behind.
BAT_MIGRATIONS = REPO_ROOT / "services" / "bat-service" / "migrations"
BALL_MIGRATIONS = REPO_ROOT / "services" / "ball-service" / "migrations"


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
    """Apply base + identity + bat + ball migrations once (idempotent).

    Sync fixture — must NOT be async, because ``upgrade_head`` uses
    ``asyncio.run`` internally and would collide with the pytest-asyncio
    event loop if called from an async fixture.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    upgrade_head(url, migrations_dir=BAT_MIGRATIONS)
    upgrade_head(url, migrations_dir=BALL_MIGRATIONS)
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
                {"id": tid, "name": f"ball-svc-{uuid.uuid4().hex[:8]}"},
            )
        yield tid
    finally:
        await engine.dispose()
