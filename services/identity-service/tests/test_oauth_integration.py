"""OAuth / SSO flow (M02 Step 7).

Uses a StubProvider injected into the app's provider registry so the full
init -> callback -> account-link -> JWT flow runs without real vendor calls.
Proves AC-M02-01's SSO variant: OAuth login issues equivalent CIP tokens.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import jwt as pyjwt
import pytest
import pytest_asyncio

from cip_data.migrations import upgrade_head
from identity_service.domain.oauth import OAuthIdentity
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


class StubProvider:
    """A fake OAuth provider — returns a fixed identity on code exchange."""

    name = "stub"

    def __init__(self, email: str, subject: str) -> None:
        self._email = email
        self._subject = subject

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://stub.example/authorize?state={state}&redirect_uri={redirect_uri}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthIdentity:
        return OAuthIdentity(subject=self._subject, email=self._email)


@pytest_asyncio.fixture
async def client_and_stub(
    migrated_db: str,
) -> AsyncIterator[tuple[httpx.AsyncClient, StubProvider]]:
    _ = migrated_db
    app = create_app()
    stub = StubProvider(
        email=f"sso-{uuid.uuid4().hex[:8]}@fake-cricket.io",
        subject=f"stub-sub-{uuid.uuid4().hex}",
    )
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with app.router.lifespan_context(app):
        # Inject the stub into the live registry built by the lifespan.
        app.state.deps.oauth_providers["stub"] = stub
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac, stub


class TestOAuthFlow:
    async def test_full_sso_login_issues_tokens(
        self, client_and_stub: tuple[httpx.AsyncClient, StubProvider]
    ) -> None:
        client, _stub = client_and_stub

        init = await client.post(
            "/v1/auth/oauth/stub/init",
            json={"redirect_uri": "http://localhost:5180/callback"},
        )
        assert init.status_code == 200, init.text
        state = init.json()["state"]
        assert init.json()["authorization_url"].startswith("https://stub.example/")

        cb = await client.post(
            "/v1/auth/oauth/stub/callback",
            json={
                "code": "fake-auth-code",
                "state": state,
                "redirect_uri": "http://localhost:5180/callback",
            },
        )
        assert cb.status_code == 200, cb.text
        body = cb.json()
        assert body["token_type"] == "Bearer"
        assert body["access_token"]
        # The token is a real CIP access token.
        claims = pyjwt.decode(body["access_token"], options={"verify_signature": False})
        assert claims["type"] == "access"
        assert uuid.UUID(claims["sub"])

    async def test_second_login_same_subject_reuses_person(
        self, client_and_stub: tuple[httpx.AsyncClient, StubProvider]
    ) -> None:
        client, _stub = client_and_stub

        async def _login() -> str:
            init = await client.post(
                "/v1/auth/oauth/stub/init",
                json={"redirect_uri": "http://localhost:5180/cb"},
            )
            cb = await client.post(
                "/v1/auth/oauth/stub/callback",
                json={
                    "code": "code",
                    "state": init.json()["state"],
                    "redirect_uri": "http://localhost:5180/cb",
                },
            )
            claims = pyjwt.decode(cb.json()["access_token"], options={"verify_signature": False})
            return str(claims["sub"])

        first = await _login()
        second = await _login()
        # Same provider subject -> same person id both times.
        assert first == second

    async def test_bad_state_rejected(
        self, client_and_stub: tuple[httpx.AsyncClient, StubProvider]
    ) -> None:
        client, _stub = client_and_stub
        cb = await client.post(
            "/v1/auth/oauth/stub/callback",
            json={
                "code": "code",
                "state": "never-issued-state",
                "redirect_uri": "http://localhost:5180/cb",
            },
        )
        assert cb.status_code == 400
        assert "state" in cb.json()["error"]["message"].lower()

    async def test_unconfigured_provider_404(
        self, client_and_stub: tuple[httpx.AsyncClient, StubProvider]
    ) -> None:
        client, _stub = client_and_stub
        r = await client.post(
            "/v1/auth/oauth/google/init",
            json={"redirect_uri": "http://localhost:5180/cb"},
        )
        # No Google credentials configured in the test env.
        assert r.status_code == 404
        assert "not configured" in r.json()["error"]["message"].lower()
