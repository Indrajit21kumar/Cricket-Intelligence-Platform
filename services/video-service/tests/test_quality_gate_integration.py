"""Quality gate end-to-end (M05 Step 6, FR-M05-06, NFR-M05-02, AC-M05-02)."""

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


class TestGatePass:
    async def test_good_clip_admitted(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["admitted"] is True
        assert r.json()["flags"] == []


class TestGateHardFail:
    async def test_bad_clip_rejected_422_with_reasons(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M05-02: a labelled bad clip hard-fails with actionable reasons (422)."""
        app, client = app_client
        created = await _create(client, tenant_id)
        # A dark, low-res, blurry clip.
        app.state.deps.video_processor.patch(width=640, height=480, blur_score=0.9, exposure=0.05)
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 422, r.text
        reasons = r.json()["error"]["details"]["reasons"]
        assert "resolution_too_low" in reasons
        assert "excessive_blur" in reasons
        assert "underexposed" in reasons

    async def test_rejection_is_persisted(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The rejection + flags are recorded even though the client got 422."""
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(duration_s=0.5)  # too short -> fail
        await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )

        r = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        assert r.status_code == 200
        assert r.json()["status"] == "rejected"


class TestGateSoftFlag:
    async def test_marginal_clip_admitted_with_soft_flag(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        created = await _create(client, tenant_id)
        # Unsupported angle -> soft flag only, still admitted.
        app.state.deps.video_processor.patch(angle_hint="square", angle_confidence=0.9)
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["admitted"] is True
        codes = {f["code"] for f in r.json()["flags"]}
        assert "unsupported_camera_angle" in codes
        assert all(f["severity"] == "flag" for f in r.json()["flags"])


class TestCostGuard:
    async def test_gate_runs_before_any_publish(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """NFR-M05-02: a rejected clip never advances (no downstream/GPU work).

        A hard-failed clip returns 422 and its status is 'rejected' — it is
        never admitted, so publishing (Step 7 -> downstream GPU stages) is not
        reached.
        """
        app, client = app_client
        created = await _create(client, tenant_id)
        app.state.deps.video_processor.patch(batter_in_frame=0.2)  # framing fail
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 422
        got = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        assert got.json()["status"] == "rejected"
