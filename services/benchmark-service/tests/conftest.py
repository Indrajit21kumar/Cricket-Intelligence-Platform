"""Shared fixtures for benchmark-service tests."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from benchmark_service.main import create_app
from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
# M15 read access is consent-scoped, so the identity schema must exist for the
# integration tests.
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"
BENCHMARK_MIGRATIONS = REPO_ROOT / "services" / "benchmark-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply base + identity + benchmark migrations once (idempotent)."""
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    upgrade_head(url, migrations_dir=BENCHMARK_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def integration_app(
    _migrated_database: str,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest_asyncio.fixture
async def tenant_id(_migrated_database: str) -> uuid.UUID:
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
                {"id": tid, "name": f"bmk-svc-{uuid.uuid4().hex[:8]}"},
            )
        yield tid
    finally:
        await engine.dispose()
