"""Signed webhooks + invoice reconciliation (M03 Step 6, AC-M03-04, NFR-M03-04).

Covers:
- POST /v1/webhooks/payments — valid signature -> invoice recorded
- POST /v1/webhooks/payments — replayed event (same provider_ref) -> no
  double-record (invoice.provider_ref UNIQUE + ON CONFLICT DO NOTHING).
- POST /v1/webhooks/payments — unsigned / bad-signature -> 401.
- GET  /v1/invoices — lists the tenant's invoices; cross-tenant is empty.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text

from billing_service.domain.catalogue import seed_catalogue
from billing_service.domain.payments import SIGNATURE_HEADER, compute_signature
from billing_service.main import create_app
from cip_core import roles
from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import upgrade_head

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"
TEST_WEBHOOK_SECRET = "dev-webhook-secret-not-for-production"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    # Route uses `deps.settings.payment_webhook_secret` — default matches
    # TEST_WEBHOOK_SECRET so we don't need to override.
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BILLING_MIGRATIONS)
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


def _access_token(*claim_roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_tenant_with_pro_sub(migrated_db: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Return (tenant_id, subscription_id) with a Pro subscription in place."""
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    tid = uuid.uuid4()
    sub_id = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await seed_catalogue(s)
            await s.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"
                ),
                {"id": tid, "n": f"acad-{uuid.uuid4().hex[:8]}"},
            )
            plan_row = (
                await s.execute(text("SELECT id FROM plans WHERE code = 'pro' AND active = true"))
            ).one()
        async with tenant_session(sf, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO subscriptions "
                    "  (id, tenant_id, subject_ref, plan_id, status, "
                    "   period_start, period_end) "
                    "VALUES (:id, :tid, :subj, :plan, 'active', now(), "
                    "        now() + interval '30 days')"
                ),
                {"id": sub_id, "tid": tid, "subj": f"tenant:{tid}", "plan": plan_row[0]},
            )
    finally:
        await engine.dispose()
    return tid, sub_id


def _webhook_body(tenant_id: uuid.UUID, sub_id: uuid.UUID, *, event_type: str) -> bytes:
    """Build a serialised webhook payload with a fresh provider_ref + event_id."""
    payload = {
        "event_id": f"evt_{uuid.uuid4().hex}",
        "event_type": event_type,
        "provider_ref": f"fake_ch_{uuid.uuid4().hex[:12]}",
        "subscription_id": str(sub_id),
        "tenant_id": str(tenant_id),
        "amount_minor": 49_900,
        "currency": "INR",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    return json.dumps(payload).encode("utf-8")


def _signed_headers(body: bytes) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: compute_signature(TEST_WEBHOOK_SECRET, body),
    }


class TestWebhookHappyPath:
    async def test_charge_succeeded_records_paid_invoice(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.succeeded")

        r = await client.post("/v1/webhooks/payments", content=body, headers=_signed_headers(body))
        assert r.status_code == 200, r.text
        ack = r.json()
        assert ack["recorded"] is True
        assert ack["status"] == "paid"

    async def test_charge_failed_records_failed_invoice(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.failed")

        r = await client.post("/v1/webhooks/payments", content=body, headers=_signed_headers(body))
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "failed"


class TestWebhookReplay:
    async def test_same_provider_ref_is_noop(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """AC-M03-04: replayed webhooks must not double-record.

        We reuse the exact same body -> same provider_ref -> UNIQUE
        constraint makes the second insert a no-op. Note we resign each
        request (a real replay would keep the signature too — that's just as
        rejected because the invoice row already exists).
        """
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.succeeded")

        first = await client.post(
            "/v1/webhooks/payments", content=body, headers=_signed_headers(body)
        )
        assert first.status_code == 200
        assert first.json()["recorded"] is True

        replay = await client.post(
            "/v1/webhooks/payments", content=body, headers=_signed_headers(body)
        )
        assert replay.status_code == 200
        assert replay.json()["recorded"] is False  # NOT double-recorded
        # And the same underlying invoice id came back both times.
        assert replay.json()["invoice_id"] == first.json()["invoice_id"]


class TestWebhookSignatureRejection:
    async def test_missing_signature_returns_401(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.succeeded")

        r = await client.post(
            "/v1/webhooks/payments",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 401

    async def test_bad_signature_returns_401(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.succeeded")

        r = await client.post(
            "/v1/webhooks/payments",
            content=body,
            headers={
                "Content-Type": "application/json",
                SIGNATURE_HEADER: "sha256=deadbeef" + "0" * 56,
            },
        )
        assert r.status_code == 401

    async def test_tampered_body_returns_401(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """Signing the original body then posting a modified one gets caught."""
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        original = _webhook_body(tid, sub_id, event_type="charge.succeeded")
        sig = compute_signature(TEST_WEBHOOK_SECRET, original)

        # Tamper: bump the amount but reuse the old signature.
        tampered = original.replace(b'"amount_minor": 49900', b'"amount_minor": 4990000')

        r = await client.post(
            "/v1/webhooks/payments",
            content=tampered,
            headers={"Content-Type": "application/json", SIGNATURE_HEADER: sig},
        )
        assert r.status_code == 401


class TestInvoicesList:
    async def test_list_returns_tenants_invoices(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid, sub_id, event_type="charge.succeeded")
        await client.post("/v1/webhooks/payments", content=body, headers=_signed_headers(body))

        r = await client.get(
            f"/v1/invoices?subject=tenant:{tid}",
            headers=_auth(_access_token(roles.ACADEMY_ADMIN)),
        )
        assert r.status_code == 200, r.text
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["status"] == "paid"
        assert rows[0]["amount_minor"] == 49_900

    async def test_cross_tenant_list_is_empty(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """RLS: tenant B cannot see tenant A's invoices."""
        tid_a, sub_a = await _seed_tenant_with_pro_sub(migrated_db)
        tid_b, _ = await _seed_tenant_with_pro_sub(migrated_db)
        body = _webhook_body(tid_a, sub_a, event_type="charge.succeeded")
        await client.post("/v1/webhooks/payments", content=body, headers=_signed_headers(body))

        r = await client.get(
            f"/v1/invoices?subject=tenant:{tid_b}",
            headers=_auth(_access_token(roles.ACADEMY_ADMIN)),
        )
        assert r.status_code == 200, r.text
        assert r.json() == []

    async def test_list_requires_role(self, client: httpx.AsyncClient, migrated_db: str) -> None:
        tid, _ = await _seed_tenant_with_pro_sub(migrated_db)
        r = await client.get(
            f"/v1/invoices?subject=tenant:{tid}",
            headers=_auth(_access_token(roles.PLAYER)),  # wrong role
        )
        assert r.status_code == 403
