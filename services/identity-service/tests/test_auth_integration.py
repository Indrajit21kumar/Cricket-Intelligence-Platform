"""End-to-end integration tests for register → verify-email → login (AC-M02-01).

These run the full FastAPI app under its real lifespan against live Postgres.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import httpx
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
    """Apply base + identity migrations once per module (sync fixture)."""
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    """AsyncClient bound to the wired identity-service app."""
    _ = migrated_db  # ensure fixture ordering
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


def _fresh_email() -> str:
    """Unique email per test — the DB is shared with other integration runs."""
    return f"user-{uuid.uuid4().hex[:8]}@fake-cricket.io"


class TestRegisterHappyPath:
    async def test_adult_can_register(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={
                "email": _fresh_email(),
                "password": "correct-horse-battery",
                "dob": "1990-05-15",
                "display_name": "Test User",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "pending_verification"
        assert body["verification_url_hint"]

    async def test_missing_idempotency_key_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            json={
                "email": _fresh_email(),
                "password": "a-password-that-is-long-enough",
                "dob": "1990-01-01",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"

    async def test_duplicate_email_is_409(self, client: httpx.AsyncClient) -> None:
        email = _fresh_email()
        payload = {
            "email": email,
            "password": "abcdef123456ABC",
            "dob": "1990-01-01",
        }
        headers = {"Idempotency-Key": f"idem-{uuid.uuid4().hex}"}

        r1 = await client.post("/v1/auth/register", json=payload, headers=headers)
        assert r1.status_code == 201

        r2 = await client.post(
            "/v1/auth/register",
            json=payload,
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "CONFLICT"

    async def test_short_password_rejected(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={
                "email": _fresh_email(),
                "password": "short",
                "dob": "1990-01-01",
            },
        )
        # pydantic validation errors map to 400 via cip_core's
        # validation_error_handler (Book 3 §3.4 "400 Malformed request").
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"


class TestVerifyEmail:
    async def test_full_register_verify_login_for_adult(self, client: httpx.AsyncClient) -> None:
        email = _fresh_email()
        password = "some-long-password-1234"

        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={"email": email, "password": password, "dob": "1990-01-01"},
        )
        assert reg.status_code == 201
        token = reg.json()["verification_url_hint"]

        verify = await client.post("/v1/auth/verify-email", json={"token": token})
        assert verify.status_code == 200, verify.text
        assert verify.json()["status"] == "active"

        login = await client.post("/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 200
        body = login.json()
        assert body["person_id"] == verify.json()["person_id"]
        assert body["session_placeholder"]

    async def test_token_replay_blocked(self, client: httpx.AsyncClient) -> None:
        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={
                "email": _fresh_email(),
                "password": "another-long-password-99",
                "dob": "1990-01-01",
            },
        )
        token = reg.json()["verification_url_hint"]

        first = await client.post("/v1/auth/verify-email", json={"token": token})
        assert first.status_code == 200

        second = await client.post("/v1/auth/verify-email", json={"token": token})
        assert second.status_code == 404  # already claimed

    async def test_bad_token_is_404(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/verify-email",
            json={"token": "not-a-real-token-at-all-1234"},
        )
        assert response.status_code == 404


class TestMinorVerificationTransitionsToPendingConsent:
    async def test_minor_dob_lands_in_pending_consent(self, client: httpx.AsyncClient) -> None:
        # 10-year-old today
        this_year = date.today().year
        minor_dob = date(this_year - 10, 1, 1).isoformat()
        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={
                "email": _fresh_email(),
                "password": "minor-account-password",
                "dob": minor_dob,
            },
        )
        assert reg.status_code == 201

        verify = await client.post(
            "/v1/auth/verify-email",
            json={"token": reg.json()["verification_url_hint"]},
        )
        assert verify.status_code == 200
        # Minors don't jump to 'active' — they wait for Step 6's guardian consent.
        assert verify.json()["status"] == "pending_consent"

    async def test_minor_login_blocked(self, client: httpx.AsyncClient) -> None:
        this_year = date.today().year
        minor_dob = date(this_year - 12, 6, 1).isoformat()
        password = "minor-cannot-login-yet"
        email = _fresh_email()

        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={"email": email, "password": password, "dob": minor_dob},
        )
        await client.post(
            "/v1/auth/verify-email",
            json={"token": reg.json()["verification_url_hint"]},
        )

        login = await client.post("/v1/auth/login", json={"email": email, "password": password})
        assert login.status_code == 400
        assert "consent" in login.json()["error"]["message"].lower()


class TestLoginSafety:
    async def test_unknown_email_returns_generic_401(self, client: httpx.AsyncClient) -> None:
        response = await client.post(
            "/v1/auth/login",
            json={"email": "does-not-exist@fake-cricket.io", "password": "whatever"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid email or password"

    async def test_wrong_password_returns_same_401(self, client: httpx.AsyncClient) -> None:
        email = _fresh_email()
        reg = await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={"email": email, "password": "the-right-password-123", "dob": "1990-01-01"},
        )
        await client.post(
            "/v1/auth/verify-email",
            json={"token": reg.json()["verification_url_hint"]},
        )

        response = await client.post(
            "/v1/auth/login",
            json={"email": email, "password": "wrong-password-1234"},
        )
        assert response.status_code == 401
        # Same shape as unknown-email — no enumeration.
        assert response.json()["error"]["message"] == "Invalid email or password"

    async def test_unverified_email_cannot_login(self, client: httpx.AsyncClient) -> None:
        email = _fresh_email()
        pw = "cannot-login-yet-password"
        await client.post(
            "/v1/auth/register",
            headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
            json={"email": email, "password": pw, "dob": "1990-01-01"},
        )
        response = await client.post("/v1/auth/login", json={"email": email, "password": pw})
        assert response.status_code == 400
        assert "not yet verified" in response.json()["error"]["message"].lower()
