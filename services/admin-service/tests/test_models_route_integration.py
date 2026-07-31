"""Route-level integration test for GET /v1/admin/models (M20 Step 5)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from admin_service.domain import model_metrics_repo
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


async def test_models_returns_one_entry_per_known_model(
    integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
) -> None:
    computed_at = datetime.now(UTC)
    async with admin_session(session_factory) as s:
        await model_metrics_repo.record_model_metric(
            s,
            model_name="pose",
            model_version="fake-pose-v1",
            metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
            value=0.93,
            computed_at=computed_at,
        )

    r = await integration_app.get("/v1/admin/models", headers=_admin_headers(uuid.uuid4()))
    assert r.status_code == 200, r.text
    body = r.json()
    names = {m["model_name"] for m in body}
    assert names == {"pose", "bat", "ball", "shot"}
    pose_entry = next(m for m in body if m["model_name"] == "pose")
    assert pose_entry["latest_accuracy"] == pytest.approx(0.93)


async def test_models_requires_platform_admin(integration_app: httpx.AsyncClient) -> None:
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
    r = await integration_app.get("/v1/admin/models", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
