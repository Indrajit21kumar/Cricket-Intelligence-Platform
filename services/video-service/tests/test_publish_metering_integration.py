"""Publish video.normalized + meter analysis.consumed (M05 Step 7).

Covers AC-M05-01 (admitted clip -> video.normalized with calibration/angle/
flags) and AC-M05-05 (exactly one analysis.consumed per admitted clip,
idempotent on re-delivery).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI

from cip_core import roles
from cip_events import EventEnvelope, KafkaEventBus
from video_service.main import create_app
from video_service.routes import TOPIC_VIDEO_NORMALIZED

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"
DEFAULT_BOOTSTRAP = "localhost:9092"


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


class TestMetering:
    async def test_admitted_clip_records_usage_once(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M05-05: exactly one analysis.consumed, idempotent on re-delivery."""
        app, client = app_client
        created = await _create(client, tenant_id)

        first = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "normalized"
        assert first.json()["usage_recorded"] is True

        # Re-deliver the same clip.
        second = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert second.status_code == 200
        assert second.json()["usage_recorded"] is False  # not double-counted

        # The fake M03 client saw exactly one metered key.
        assert len(app.state.deps.entitlement_client.recorded) == 1

    async def test_rejected_clip_does_not_meter(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(width=640, height=480)  # hard fail
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 422
        # No usage recorded for a rejected clip.
        assert len(app.state.deps.entitlement_client.recorded) == 0


class TestPublish:
    async def test_admitted_clip_publishes_video_normalized(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M05-01: video.normalized carries calibration + angle + flags."""
        _app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m05-norm-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_VIDEO_NORMALIZED, group_id=group)

            created = await _create(client, tenant_id)
            r = await client.post(
                f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
            )
            assert r.status_code == 200, r.text

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if str(env.payload.get("ingestion_id")) == str(created["ingestion_id"]):
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.tenant_id == tenant_id
            assert env.payload["camera_angle"] == "side_on"
            assert env.payload["spatial_confidence"] == "high"
            assert env.payload["normalized_ref"] == created["raw_ref"].replace(
                "/raw/", "/normalized/"
            )
            assert env.payload["depth_estimated"] is True
        finally:
            await bus.stop()
