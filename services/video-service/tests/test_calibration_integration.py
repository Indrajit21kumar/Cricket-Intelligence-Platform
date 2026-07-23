"""Calibration end-to-end (M05 Step 5, FR-M05-05, NFR-M05-03, AC-M05-03).

Every calibration carries spatial_confidence + depth_estimated (Book 4 §2.3).
"""

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


async def _complete(
    client: httpx.AsyncClient, tenant_id: uuid.UUID, ingestion_id: str
) -> dict[str, object]:
    r = await client.post(f"/v1/videos/{ingestion_id}/complete", headers=_headers(tenant_id))
    assert r.status_code == 200, r.text
    return r.json()


class TestCalibration:
    async def test_stump_visible_high_confidence(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M05-03: default (stumps in frame, side-on) -> high + depth_estimated."""
        _app, client = app_client
        created = await _create(client, tenant_id)
        body = await _complete(client, tenant_id, created["ingestion_id"])
        assert body["calibration_method"] == "stump"
        assert body["spatial_confidence"] == "high"
        assert body["depth_estimated"] is True
        assert body["pixel_to_meter"] is not None

    async def test_no_stump_uses_height_fallback_medium(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        # No stumps in frame; M04 has the player's height.
        app.state.deps.video_processor.patch(stump_visible=False, stump_pixel_height=None)
        app.state.deps.profile_client.height_cm = 178.0

        body = await _complete(client, tenant_id, created["ingestion_id"])
        assert body["calibration_method"] == "height"
        assert body["spatial_confidence"] == "medium"

    async def test_neither_reference_low_uncalibrated(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(stump_visible=False, stump_pixel_height=None)
        app.state.deps.profile_client.height_cm = None  # unknown height

        body = await _complete(client, tenant_id, created["ingestion_id"])
        assert body["calibration_method"] == "none"
        assert body["spatial_confidence"] == "low"
        assert body["pixel_to_meter"] is None

    async def test_unsupported_angle_caps_confidence_low(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """Stumps visible but a square angle -> scale derived, confidence low."""
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(angle_hint="square", angle_confidence=0.9)

        body = await _complete(client, tenant_id, created["ingestion_id"])
        assert body["calibration_method"] == "stump"
        assert body["spatial_confidence"] == "low"

    async def test_calibration_persisted_in_get(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)
        await _complete(client, tenant_id, created["ingestion_id"])

        r = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        cal = r.json()["calibration"]
        assert cal["spatial_confidence"] == "high"
        assert cal["method"] == "stump"
        assert cal["depth_estimated"] is True
