"""Quality-result API + capture-guidance contract (M05 Step 8, FR-M05-10, §11)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI

from cip_core import roles
from video_service.domain.quality_gate import capture_thresholds
from video_service.main import create_app

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


@pytest_asyncio.fixture
async def app_client(
    _migrated_database: str,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield app, ac


def _token(*claim_roles: str) -> str:
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


def _headers(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(roles.PLAYER)}", "X-Tenant-ID": str(tenant_id)}


def _body() -> dict[str, object]:
    return {
        "person_id": str(uuid.uuid4()),
        "source_type": "mobile",
        "content_type": "video/mp4",
        "size_bytes": 4_000_000,
    }


async def _create(client: httpx.AsyncClient, tenant_id: uuid.UUID) -> dict[str, object]:
    r = await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
    assert r.status_code == 201, r.text
    return r.json()


class TestQualityResult:
    async def test_admitted_clip_quality_result(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)
        await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        r = await client.get(
            f"/v1/videos/{created['ingestion_id']}/quality", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["admitted"] is True
        assert r.json()["flags"] == []

    async def test_rejected_clip_quality_result_has_reasons(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """FR-M05-10: the re-film UX can read the actionable fail flags."""
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(width=640, height=480, blur_score=0.9)
        await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )

        r = await client.get(
            f"/v1/videos/{created['ingestion_id']}/quality", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["admitted"] is False
        assert body["status"] == "rejected"
        codes = {f["code"] for f in body["flags"]}
        assert "resolution_too_low" in codes
        assert "excessive_blur" in codes
        # Every flag carries an actionable message.
        assert all(f["message"] for f in body["flags"])

    async def test_quality_unknown_ingestion_404(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.get(f"/v1/videos/{uuid.uuid4()}/quality", headers=_headers(tenant_id))
        assert r.status_code == 404


class TestCaptureGuidance:
    async def test_guidance_returns_thresholds(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.get("/v1/capture-guidance", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        thresholds = r.json()["thresholds"]
        # Same numbers the gate uses (§11: guidance and gate never disagree).
        assert thresholds == capture_thresholds()
        assert "side_on" in thresholds["supported_angles"]
        assert thresholds["min_width"] == 1280

    async def test_guidance_requires_auth(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.get("/v1/capture-guidance")
        assert r.status_code == 401
