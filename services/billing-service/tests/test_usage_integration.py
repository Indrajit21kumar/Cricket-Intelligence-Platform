"""Idempotent usage metering (M03 Step 4, AC-M03-03, NFR-M03-02)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from billing_service.domain.catalogue import seed_catalogue
from billing_service.main import create_app
from cip_data.engine import (
    admin_session,
    build_engine,
    build_session_factory,
    tenant_session,
)
from cip_data.migrations import upgrade_head

pytestmark = pytest.mark.integration

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


async def _seed_starter_subscription(migrated_db: str) -> uuid.UUID:
    """Create a tenant + a starter subscription (quota 5). Returns tenant_id."""
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        # Catalogue + tenant are global/no-RLS -> admin_session.
        async with admin_session(sf) as s:
            await seed_catalogue(s)
            await s.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"
                ),
                {"id": tid, "n": f"acad-{uuid.uuid4().hex[:8]}"},
            )
            plan = (
                await s.execute(
                    text("SELECT id FROM plans WHERE code = 'starter' AND active = true")
                )
            ).first()
        # subscriptions is RLS-scoped -> insert under a tenant_session for tid.
        async with tenant_session(sf, tenant_id=tid) as s:
            await s.execute(
                text(
                    "INSERT INTO subscriptions "
                    "  (id, tenant_id, subject_ref, plan_id, status, "
                    "   period_start, period_end) "
                    "VALUES (:id, :tid, :subj, :plan, 'active', now(), "
                    "        now() + interval '30 days')"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tid,
                    "subj": f"tenant:{tid}",
                    "plan": plan[0],
                },
            )
    finally:
        await engine.dispose()
    return tid


class TestUsageMetering:
    async def test_usage_recorded_and_counter_increments(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_starter_subscription(migrated_db)
        subject = f"tenant:{tid}"

        r = await client.post(
            "/v1/usage",
            headers={"Idempotency-Key": f"u-{uuid.uuid4().hex}"},
            json={"subject": subject, "meter_key": "analysis.consumed", "qty": 1},
        )
        assert r.status_code == 200, r.text
        assert r.json()["recorded"] is True
        assert r.json()["total"] == 1

    async def test_duplicate_idempotency_key_is_noop(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_starter_subscription(migrated_db)
        subject = f"tenant:{tid}"
        key = f"u-{uuid.uuid4().hex}"

        first = await client.post(
            "/v1/usage",
            headers={"Idempotency-Key": key},
            json={"subject": subject},
        )
        assert first.json()["recorded"] is True
        assert first.json()["total"] == 1

        # Same idempotency key -> exactly-once no-op (AC-M03-03).
        dup = await client.post(
            "/v1/usage",
            headers={"Idempotency-Key": key},
            json={"subject": subject},
        )
        assert dup.json()["recorded"] is False
        assert dup.json()["total"] == 1  # NOT double-counted

    async def test_usage_decrements_entitlement_remaining(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_starter_subscription(migrated_db)
        subject = f"tenant:{tid}"

        # Starter quota is 5. Consume 3 distinct events.
        for _ in range(3):
            await client.post(
                "/v1/usage",
                headers={"Idempotency-Key": f"u-{uuid.uuid4().hex}"},
                json={"subject": subject},
            )

        chk = await client.post(
            "/v1/entitlements/check",
            json={"subject": subject, "key": "analysis.quota_monthly"},
        )
        assert chk.status_code == 200, chk.text
        body = chk.json()
        assert body["remaining"] == 2  # 5 - 3
        assert body["allowed"] is True

    async def test_usage_without_subscription_404(self, client: httpx.AsyncClient) -> None:
        subject = f"tenant:{uuid.uuid4()}"  # tenant with no subscription
        r = await client.post(
            "/v1/usage",
            headers={"Idempotency-Key": f"u-{uuid.uuid4().hex}"},
            json={"subject": subject},
        )
        assert r.status_code == 404
