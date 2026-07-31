"""Shared fixtures for admin-service tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from admin_service.main import create_app
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_core.settings import get_settings
from cip_data.engine import build_engine, build_session_factory
from cip_data.migrations import upgrade_head

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
ADMIN_MIGRATIONS = REPO_ROOT / "services" / "admin-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply base + admin migrations once (idempotent)."""
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=ADMIN_MIGRATIONS)
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
async def _engine(_migrated_database: str) -> AsyncIterator[AsyncEngine]:
    engine = build_engine(_migrated_database)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(_engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(_engine)
