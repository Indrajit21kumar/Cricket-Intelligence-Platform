"""Route-level integration test for GET /v1/admin/analytics (M20 Step 4)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import roles
from cip_data.engine import admin_session

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


def _admin_headers(admin_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "type": "access",
            "roles": [roles.PLATFORM_ADMIN],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


async def test_analytics_reflects_seeded_facts_in_the_default_window(
    integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
) -> None:
    now = datetime.now(UTC)
    async with admin_session(session_factory) as s:
        await s.execute(
            text(
                "INSERT INTO warehouse.fact_revenue_event "
                "  (id, event_topic, tenant_id, occurred_at, dedupe_key, amount_minor, currency) "
                "VALUES (:id, 'billing.invoice.paid', :tid, :now, :dedupe, 1500, 'USD')"
            ),
            {
                "id": uuid.uuid4(),
                "tid": uuid.uuid4(),
                "now": now,
                "dedupe": f"route-{uuid.uuid4()}",
            },
        )
        await s.execute(
            text(
                "INSERT INTO warehouse.fact_usage_event "
                "  (id, event_topic, tenant_id, correlation_id, occurred_at, dedupe_key, payload) "
                "VALUES (:id, 'video.normalized', :tid, :corr, :now, :dedupe, cast(:p as jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "tid": uuid.uuid4(),
                "corr": f"route-corr-{uuid.uuid4().hex}",
                "now": now,
                "dedupe": f"route-usage-{uuid.uuid4()}",
                "p": json.dumps({}),
            },
        )

    r = await integration_app.get("/v1/admin/analytics", headers=_admin_headers(uuid.uuid4()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["revenue"]["revenue_minor_by_currency"].get("USD", 0) >= 1500
    assert body["revenue"]["invoice_count"] >= 1
    assert body["usage"]["analyses_started"] >= 1
    assert "video.normalized" in body["usage"]["events_by_topic"]


async def test_analytics_requires_platform_admin(integration_app: httpx.AsyncClient) -> None:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "roles": [roles.COACH],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    r = await integration_app.get(
        "/v1/admin/analytics", headers={"Authorization": f"Bearer {token}"}
    )
    assert r.status_code == 403
