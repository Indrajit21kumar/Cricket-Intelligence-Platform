"""Route-level integration tests for /v1/admin/audit and /v1/admin/success-metrics (M20 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from admin_service.domain.audit import record_admin_action
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import roles
from cip_data.engine import admin_session

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


def _headers(person_id: uuid.UUID, *claim_roles: str) -> dict[str, str]:
    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(person_id),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


class TestAuditRoute:
    async def test_search_finds_a_platform_action_by_actor(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        actor = str(uuid.uuid4())
        async with admin_session(session_factory) as s:
            await record_admin_action(
                s, admin_ref=actor, action="content.removed", target=f"clip:{uuid.uuid4()}"
            )
        r = await integration_app.get(
            "/v1/admin/audit",
            params={"actor": actor},
            headers=_headers(uuid.uuid4(), roles.PLATFORM_ADMIN),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body) == 1
        assert body[0]["actor"] == actor

    async def test_requires_platform_admin(self, integration_app: httpx.AsyncClient) -> None:
        r = await integration_app.get(
            "/v1/admin/audit", headers=_headers(uuid.uuid4(), roles.COACH)
        )
        assert r.status_code == 403


class TestSuccessMetricsRoute:
    async def test_returns_the_kpi_shape(self, integration_app: httpx.AsyncClient) -> None:
        r = await integration_app.get(
            "/v1/admin/success-metrics", headers=_headers(uuid.uuid4(), roles.PLATFORM_ADMIN)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "total_academies" in body
        assert "countries" in body
        assert "average_model_accuracy" in body
        assert "retention_rate" in body
        assert "inference_time" not in body  # never fabricated -- see module docstring

    async def test_requires_platform_admin(self, integration_app: httpx.AsyncClient) -> None:
        r = await integration_app.get(
            "/v1/admin/success-metrics", headers=_headers(uuid.uuid4(), roles.COACH)
        )
        assert r.status_code == 403
