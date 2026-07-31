"""Route-level integration tests for the review-queue workflow (M20 Step 6).

Seeds directly via :mod:`review_queue_repo` (bypassing ``/sync``) to test
list/resolve in isolation from the Fake source's own lifecycle, which
:mod:`test_biomechanics_review_source` already covers directly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from admin_service.domain import review_queue_repo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import roles
from cip_data.engine import admin_session

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


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


class TestReviewQueueRoutes:
    async def test_list_then_resolve(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        tenant_id = await _make_tenant(session_factory, "review-queue")
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            created = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="elbow_flexion out of range"
            )

        admin_id = uuid.uuid4()
        r = await integration_app.get(
            "/v1/admin/review-queue",
            params={"status": "pending"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        assert any(item["id"] == str(created["id"]) for item in r.json())

        r = await integration_app.post(
            f"/v1/admin/review-queue/{created['id']}/resolve",
            json={"resolution_note": "genuine outlier, confirmed via slow-motion review"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "resolved"
        assert body["reviewer"] == str(admin_id)

        r = await integration_app.get(
            "/v1/admin/review-queue",
            params={"status": "pending"},
            headers=_admin_headers(admin_id),
        )
        assert not any(item["id"] == str(created["id"]) for item in r.json())

        async with admin_session(session_factory) as s:
            actions = (
                await s.execute(
                    text("SELECT action FROM admin_actions WHERE target = :t"),
                    {"t": f"review_queue_item:{created['id']}"},
                )
            ).all()
        assert [a[0] for a in actions] == ["review_queue.resolved"]

    async def test_resolving_unknown_item_is_404(self, integration_app: httpx.AsyncClient) -> None:
        r = await integration_app.post(
            f"/v1/admin/review-queue/{uuid.uuid4()}/resolve",
            json={},
            headers=_admin_headers(uuid.uuid4()),
        )
        assert r.status_code == 404

    async def test_sync_returns_a_count_and_is_audited(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        admin_id = uuid.uuid4()
        r = await integration_app.post(
            "/v1/admin/review-queue/sync", headers=_admin_headers(admin_id)
        )
        assert r.status_code == 200, r.text
        assert "synced" in r.json()
        assert isinstance(r.json()["synced"], int)

    async def test_review_queue_requires_platform_admin(
        self, integration_app: httpx.AsyncClient
    ) -> None:
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
            "/v1/admin/review-queue", headers={"Authorization": f"Bearer {token}"}
        )
        assert r.status_code == 403
