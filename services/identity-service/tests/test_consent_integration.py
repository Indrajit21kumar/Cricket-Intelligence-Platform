"""Guardian-consent flow for minors (M02 Step 6 / AC-M02-04).

Proves the central invariant: a minor account cannot be activated for
processing (cannot log in) without a verified guardian consent — and that
granting consent activates them, while withdrawing it restricts them again.
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


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@fake-cricket.io"


def _minor_dob() -> str:
    return date(date.today().year - 10, 6, 1).isoformat()


async def _register_verify(client: httpx.AsyncClient, email: str, password: str, dob: str) -> dict:
    reg = await client.post(
        "/v1/auth/register",
        headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
        json={"email": email, "password": password, "dob": dob},
    )
    assert reg.status_code == 201, reg.text
    verify = await client.post(
        "/v1/auth/verify-email",
        json={"token": reg.json()["verification_url_hint"]},
    )
    assert verify.status_code == 200
    return {"person_id": reg.json()["person_id"], "status": verify.json()["status"]}


async def _login_adult(client: httpx.AsyncClient, email: str, password: str) -> str:
    r = await client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


class TestMinorGate:
    async def test_minor_blocked_until_guardian_consent(self, client: httpx.AsyncClient) -> None:
        # --- minor registers + verifies -> pending_consent, cannot log in
        minor_email = _email("minor")
        minor_pw = "minor-account-password-1"
        minor = await _register_verify(client, minor_email, minor_pw, _minor_dob())
        assert minor["status"] == "pending_consent"

        blocked = await client.post(
            "/v1/auth/login", json={"email": minor_email, "password": minor_pw}
        )
        assert blocked.status_code == 400
        assert "consent" in blocked.json()["error"]["message"].lower()

        # --- guardian (adult) registers + logs in
        guardian_email = _email("guardian")
        guardian_pw = "guardian-account-password-1"
        await _register_verify(client, guardian_email, guardian_pw, "1980-01-01")
        guardian_token = await _login_adult(client, guardian_email, guardian_pw)

        # --- guardian claims guardianship over the minor
        g = await client.post(
            "/v1/guardianships",
            headers={
                "Authorization": f"Bearer {guardian_token}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"minor_email": minor_email},
        )
        assert g.status_code == 201, g.text
        assert g.json()["verified"] is True

        # --- minor STILL cannot log in (guardianship alone isn't consent)
        still_blocked = await client.post(
            "/v1/auth/login", json={"email": minor_email, "password": minor_pw}
        )
        assert still_blocked.status_code == 400

        # --- guardian grants processing consent -> minor activated
        c = await client.post(
            "/v1/consents",
            headers={
                "Authorization": f"Bearer {guardian_token}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"minor_person_id": minor["person_id"], "type": "processing"},
        )
        assert c.status_code == 201, c.text
        assert c.json()["minor_status"] == "active"

        # --- minor can NOW log in
        ok = await client.post("/v1/auth/login", json={"email": minor_email, "password": minor_pw})
        assert ok.status_code == 200, ok.text

    async def test_consent_without_guardianship_forbidden(self, client: httpx.AsyncClient) -> None:
        minor_email = _email("minor")
        minor = await _register_verify(
            client, minor_email, "minor-account-password-2", _minor_dob()
        )
        # A random adult with NO guardianship tries to consent.
        adult_email = _email("stranger")
        await _register_verify(client, adult_email, "stranger-password-99", "1985-01-01")
        stranger_token = await _login_adult(client, adult_email, "stranger-password-99")

        r = await client.post(
            "/v1/consents",
            headers={
                "Authorization": f"Bearer {stranger_token}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"minor_person_id": minor["person_id"], "type": "processing"},
        )
        assert r.status_code == 403
        assert "guardianship" in r.json()["error"]["message"].lower()

    async def test_withdrawal_restricts_minor_again(self, client: httpx.AsyncClient) -> None:
        minor_email = _email("minor")
        minor_pw = "minor-account-password-3"
        minor = await _register_verify(client, minor_email, minor_pw, _minor_dob())

        guardian_email = _email("guardian")
        await _register_verify(client, guardian_email, "guardian-password-3", "1975-01-01")
        gtoken = await _login_adult(client, guardian_email, "guardian-password-3")

        await client.post(
            "/v1/guardianships",
            headers={
                "Authorization": f"Bearer {gtoken}",
                "Idempotency-Key": f"i-{uuid.uuid4().hex}",
            },
            json={"minor_email": minor_email},
        )
        consent = await client.post(
            "/v1/consents",
            headers={
                "Authorization": f"Bearer {gtoken}",
                "Idempotency-Key": f"i-{uuid.uuid4().hex}",
            },
            json={"minor_person_id": minor["person_id"], "type": "processing"},
        )
        consent_id = consent.json()["id"]
        # minor active now
        assert (
            await client.post("/v1/auth/login", json={"email": minor_email, "password": minor_pw})
        ).status_code == 200

        # withdraw -> minor restricted
        w = await client.post(
            f"/v1/consents/{consent_id}/withdraw",
            headers={"Authorization": f"Bearer {gtoken}"},
        )
        assert w.status_code == 200
        assert w.json()["minor_status"] == "pending_consent"

        # minor blocked again
        blocked = await client.post(
            "/v1/auth/login", json={"email": minor_email, "password": minor_pw}
        )
        assert blocked.status_code == 400

    async def test_cannot_be_own_guardian(self, client: httpx.AsyncClient) -> None:
        # Adult tries to claim guardianship over themselves (by their own email).
        email = _email("adult")
        await _register_verify(client, email, "adult-password-123", "1990-01-01")
        token = await _login_adult(client, email, "adult-password-123")
        r = await client.post(
            "/v1/guardianships",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"i-{uuid.uuid4().hex}",
            },
            json={"minor_email": email},
        )
        # Either "not a minor" or "cannot be your own guardian" — both 400.
        assert r.status_code == 400

    async def test_guardianship_over_adult_rejected(self, client: httpx.AsyncClient) -> None:
        adult_email = _email("adult")
        await _register_verify(client, adult_email, "adult-password-abc", "1992-01-01")
        guardian_email = _email("guardian")
        await _register_verify(client, guardian_email, "guardian-password-x", "1970-01-01")
        gtoken = await _login_adult(client, guardian_email, "guardian-password-x")

        r = await client.post(
            "/v1/guardianships",
            headers={
                "Authorization": f"Bearer {gtoken}",
                "Idempotency-Key": f"i-{uuid.uuid4().hex}",
            },
            json={"minor_email": adult_email},
        )
        assert r.status_code == 400
        assert "not a minor" in r.json()["error"]["message"].lower()
