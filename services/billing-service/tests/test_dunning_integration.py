"""Dunning end-to-end: failed webhook -> retry -> suspend + recovery
(M03 Step 7, AC-M03-05, FR-M03-07).

Covers:
- Single failed webhook -> subscription becomes ``past_due``.
- MAX_ATTEMPTS failed webhooks -> subscription becomes ``suspended``.
- Failed then succeeded -> subscription recovers to ``active``.
- Suspended subscription -> entitlement check denies (cache is dropped).
- Notification is published to the M19 topic on a failed charge (Kafka
  consumer confirms the event actually shipped).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from billing_service.domain.catalogue import seed_catalogue
from billing_service.domain.dunning import MAX_ATTEMPTS, NOTIFICATION_TOPIC
from billing_service.domain.payments import SIGNATURE_HEADER, compute_signature
from billing_service.main import create_app
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import upgrade_head
from cip_events import EventEnvelope, KafkaEventBus

pytestmark = pytest.mark.integration

TEST_WEBHOOK_SECRET = "dev-webhook-secret-not-for-production"
DEFAULT_BOOTSTRAP = "localhost:9092"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"


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


async def _seed_tenant_with_pro_sub(migrated_db: str) -> tuple[uuid.UUID, uuid.UUID]:
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


async def _read_status(migrated_db: str, tenant_id: uuid.UUID, sub_id: uuid.UUID) -> str:
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    try:
        async with tenant_session(sf, tenant_id=tenant_id) as s:
            row = (
                await s.execute(
                    text("SELECT status FROM subscriptions WHERE id = :id"),
                    {"id": sub_id},
                )
            ).one()
        return str(row[0])
    finally:
        await engine.dispose()


def _webhook_body(
    tenant_id: uuid.UUID, sub_id: uuid.UUID, *, event_type: str
) -> tuple[bytes, dict[str, str]]:
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
    body = json.dumps(payload).encode("utf-8")
    return body, {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: compute_signature(TEST_WEBHOOK_SECRET, body),
    }


async def _fire_failed_webhook(
    client: httpx.AsyncClient, tid: uuid.UUID, sub_id: uuid.UUID
) -> httpx.Response:
    body, headers = _webhook_body(tid, sub_id, event_type="charge.failed")
    return await client.post("/v1/webhooks/payments", content=body, headers=headers)


async def _fire_succeeded_webhook(
    client: httpx.AsyncClient, tid: uuid.UUID, sub_id: uuid.UUID
) -> httpx.Response:
    body, headers = _webhook_body(tid, sub_id, event_type="charge.succeeded")
    return await client.post("/v1/webhooks/payments", content=body, headers=headers)


class TestDunningStateTransitions:
    async def test_first_failure_marks_past_due(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        r = await _fire_failed_webhook(client, tid, sub_id)
        assert r.status_code == 200, r.text
        assert await _read_status(migrated_db, tid, sub_id) == "past_due"

    async def test_max_attempts_failures_suspend(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """After MAX_ATTEMPTS distinct failed charges the sub is suspended."""
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        for i in range(MAX_ATTEMPTS):
            r = await _fire_failed_webhook(client, tid, sub_id)
            assert r.status_code == 200, f"attempt {i + 1}: {r.text}"
        assert await _read_status(migrated_db, tid, sub_id) == "suspended"

    async def test_failed_then_succeeded_recovers(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)

        r = await _fire_failed_webhook(client, tid, sub_id)
        assert r.status_code == 200
        assert await _read_status(migrated_db, tid, sub_id) == "past_due"

        r = await _fire_succeeded_webhook(client, tid, sub_id)
        assert r.status_code == 200
        assert await _read_status(migrated_db, tid, sub_id) == "active"

    async def test_succeeded_on_active_is_a_noop(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """A renewal on an already-active sub doesn't perturb the state."""
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
        r = await _fire_succeeded_webhook(client, tid, sub_id)
        assert r.status_code == 200
        assert await _read_status(migrated_db, tid, sub_id) == "active"


class TestSuspendDeniesEntitlements:
    async def test_suspended_sub_denies_entitlements(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """After suspend the entitlement check must deny (cache dropped)."""
        tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)

        # Prime the cache while active - Pro has feature.ai_coach.
        before = await client.post(
            "/v1/entitlements/check",
            json={"subject": f"tenant:{tid}", "key": "feature.ai_coach"},
        )
        assert before.status_code == 200
        assert before.json()["allowed"] is True

        # Trip the dunning state machine into suspend.
        for _ in range(MAX_ATTEMPTS):
            r = await _fire_failed_webhook(client, tid, sub_id)
            assert r.status_code == 200

        # After suspend: no active subscription -> not allowed.
        after = await client.post(
            "/v1/entitlements/check",
            json={"subject": f"tenant:{tid}", "key": "feature.ai_coach"},
        )
        assert after.status_code == 200
        assert after.json()["allowed"] is False


class TestNotificationEmitted:
    async def test_failed_charge_emits_notification_event(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """FR-M03-07: dunning notifies via M19 — prove the event actually ships."""
        # Start the consumer BEFORE we publish so we don't miss it.
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m03-dunning-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(NOTIFICATION_TOPIC, group_id=group)

            tid, sub_id = await _seed_tenant_with_pro_sub(migrated_db)
            r = await _fire_failed_webhook(client, tid, sub_id)
            assert r.status_code == 200

            async def _find_ours() -> EventEnvelope:
                async for env in consumer_iter:
                    if str(env.payload.get("subscription_id")) == str(sub_id):
                        return env
                raise RuntimeError("consumer exhausted without our event")

            envelope = await asyncio.wait_for(_find_ours(), timeout=15.0)
            assert envelope.tenant_id == tid
            assert envelope.payload["action"] == "retry_scheduled"
            assert envelope.payload["template"] == "billing.payment_failed"
            assert envelope.payload["attempt_number"] == 1
            assert envelope.payload["next_retry_at"] is not None
        finally:
            await bus.stop()
