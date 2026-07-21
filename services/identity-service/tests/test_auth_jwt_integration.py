"""Integration tests for JWT issuance + refresh + logout (M02 Step 3, AC-M02-05)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import jwt
import pytest
import pytest_asyncio

from cip_data.migrations import upgrade_head
from identity_service.main import create_app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    _ = migrated_db
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


async def _register_verify_and_login(client: httpx.AsyncClient) -> dict[str, object]:
    """Full flow up to a fresh (access, refresh) token pair."""
    email = f"user-{uuid.uuid4().hex[:8]}@fake-cricket.io"
    password = "long-password-for-tests-1234"

    reg = await client.post(
        "/v1/auth/register",
        headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
        json={"email": email, "password": password, "dob": "1990-01-01"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["verification_url_hint"]

    verify = await client.post("/v1/auth/verify-email", json={"token": token})
    assert verify.status_code == 200

    login = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return login.json()


class TestLoginIssuesJWTPair:
    async def test_login_returns_token_response_shape(self, client: httpx.AsyncClient) -> None:
        body = await _register_verify_and_login(client)
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] > 0
        assert body["access_token"]
        assert body["refresh_token"]

    async def test_access_token_carries_subject(self, client: httpx.AsyncClient) -> None:
        body = await _register_verify_and_login(client)
        claims = jwt.decode(body["access_token"], options={"verify_signature": False})
        assert uuid.UUID(claims["sub"])
        assert claims["type"] == "access"

    async def test_refresh_token_type_is_refresh(self, client: httpx.AsyncClient) -> None:
        body = await _register_verify_and_login(client)
        claims = jwt.decode(body["refresh_token"], options={"verify_signature": False})
        assert claims["type"] == "refresh"


class TestRefreshRotation:
    async def test_refresh_swaps_pair(self, client: httpx.AsyncClient) -> None:
        first = await _register_verify_and_login(client)
        second = await client.post(
            "/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        )
        assert second.status_code == 200
        body = second.json()
        assert body["refresh_token"] != first["refresh_token"]
        assert body["access_token"] != first["access_token"]

    async def test_refresh_is_single_use(self, client: httpx.AsyncClient) -> None:
        first = await _register_verify_and_login(client)
        # Use once — succeeds
        r1 = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert r1.status_code == 200
        # Re-use — MUST fail (rotation catches replay)
        r2 = await client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert r2.status_code == 401

    async def test_invalid_refresh_rejected(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/v1/auth/refresh", json={"refresh_token": "not-a-jwt-at-all"})
        assert r.status_code == 401


class TestLogout:
    async def test_logout_revokes_presented_refresh(self, client: httpx.AsyncClient) -> None:
        tokens = await _register_verify_and_login(client)
        out = await client.post("/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]})
        assert out.status_code == 200
        assert out.json()["revoked_count"] == 1

        # Refresh with the revoked token must fail.
        r = await client.post("/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
        assert r.status_code == 401


class TestLogoutAll:
    async def test_revokes_every_refresh_for_person(self, client: httpx.AsyncClient) -> None:
        # Log in twice to produce two refresh tokens for the same person.
        email = f"user-{uuid.uuid4().hex[:8]}@fake-cricket.io"
        password = "long-password-for-tests-1234"

        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={"email": email, "password": password, "dob": "1990-01-01"},
        )
        await client.post(
            "/v1/auth/verify-email",
            json={"token": reg.json()["verification_url_hint"]},
        )
        first = (
            await client.post("/v1/auth/login", json={"email": email, "password": password})
        ).json()
        second = (
            await client.post("/v1/auth/login", json={"email": email, "password": password})
        ).json()

        # logout-all requires a valid access token
        r = await client.post(
            "/v1/auth/logout-all",
            headers={"Authorization": f"Bearer {second['access_token']}"},
        )
        assert r.status_code == 200
        assert r.json()["revoked_count"] >= 2

        # Neither refresh works any more
        for tokens in (first, second):
            resp = await client.post(
                "/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
            )
            assert resp.status_code == 401

    async def test_logout_all_requires_bearer(self, client: httpx.AsyncClient) -> None:
        r = await client.post("/v1/auth/logout-all")
        assert r.status_code == 401
