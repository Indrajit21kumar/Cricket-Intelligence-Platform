"""Preprocessing pipeline (M05 Step 3, FR-M05-03).

Covers: /complete runs preprocessing -> normalised clip + processing_results;
re-delivery is idempotent (same result row); the fake processor's measurement
seam feeds the pipeline.
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
from video_service.domain.processor import normalized_key
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


def _headers(tenant_id: uuid.UUID, *, correlation: str | None = None) -> dict[str, str]:
    h = {"Authorization": f"Bearer {_token(roles.PLAYER)}", "X-Tenant-ID": str(tenant_id)}
    if correlation:
        h["X-Correlation-ID"] = correlation
    return h


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


class TestPreprocessing:
    async def test_complete_runs_preprocessing(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)

        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # A good clip is admitted and runs to 'normalized' (later steps publish).
        assert body["status"] == "normalized"
        # Normalised clip key derives from the raw key.
        assert body["normalized_ref"] == normalized_key(created["raw_ref"])
        assert body["frame_count"] == 300  # fake good clip
        assert body["fps"] == 60.0

    async def test_get_includes_processing_details(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = await _create(client, tenant_id)
        await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )

        r = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        proc = r.json()["processing"]
        assert proc is not None
        assert proc["width"] == 1920
        assert proc["height"] == 1080
        assert proc["duration_s"] == 5.0

    async def test_reprocess_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """Re-delivery (same ingestion) upserts the same processing_results row."""
        _app, client = app_client
        created = await _create(client, tenant_id)

        first = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        second = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["normalized_ref"] == second.json()["normalized_ref"]

    async def test_processor_measurement_seam_flows_through(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The fake's injected measurements reach processing_results (720p/30fps)."""
        app, client = app_client
        created = await _create(client, tenant_id)

        # Inject a lower-res, lower-fps clip for the next preprocess call.
        app.state.deps.video_processor.patch(width=1280, height=720, fps=30.0, frame_count=150)

        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["frame_count"] == 150
        assert r.json()["fps"] == 30.0
