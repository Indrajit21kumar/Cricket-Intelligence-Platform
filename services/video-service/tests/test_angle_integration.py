"""Camera-angle detection end-to-end (M05 Step 4, FR-M05-04)."""

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


class TestAngleDetection:
    async def test_side_on_supported(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["camera_angle"] == "side_on"
        assert r.json()["angle_supported"] is True
        assert r.json()["angle_recommendation"] is None

    async def test_unsupported_angle_flags_with_recommendation(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        # Inject a square-on clip.
        app.state.deps.video_processor.patch(angle_hint="square", angle_confidence=0.9)

        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["camera_angle"] == "square"
        assert r.json()["angle_supported"] is False
        assert "side-on" in r.json()["angle_recommendation"]

    async def test_angle_persisted_in_calibration(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(angle_hint="front_on", angle_confidence=0.8)
        await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )

        r = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["calibration"]["camera_angle"] == "front_on"
