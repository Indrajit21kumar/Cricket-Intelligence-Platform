"""Signed-URL upload + validation + M03 entitlement gate (M05 Step 2).

Covers AC-M05-04 (over-quota denied with a reason), FR-M05-01 (validation),
and idempotent create on correlation_id.
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
from video_service.domain.validation import validate_upload
from video_service.main import create_app

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


@pytest_asyncio.fixture
async def app_client(
    _migrated_database: str,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    """Yield (app, client) so tests can reach app.state.deps (fake adapters)."""
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
    h = {
        "Authorization": f"Bearer {_token(roles.PLAYER)}",
        "X-Tenant-ID": str(tenant_id),
    }
    if correlation:
        h["X-Correlation-ID"] = correlation
    return h


def _body(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "person_id": str(uuid.uuid4()),
        "source_type": "mobile",
        "content_type": "video/mp4",
        "size_bytes": 4_000_000,
    }
    payload.update(overrides)
    return payload


class TestValidationUnit:
    def test_valid_upload_has_no_reasons(self) -> None:
        assert (
            validate_upload(content_type="video/mp4", source_type="mobile", size_bytes=1_000_000)
            == []
        )

    def test_bad_content_type(self) -> None:
        assert "unsupported_content_type" in validate_upload(
            content_type="image/png", source_type="mobile", size_bytes=1_000_000
        )

    def test_bad_source_type(self) -> None:
        assert "unsupported_source_type" in validate_upload(
            content_type="video/mp4", source_type="webcam", size_bytes=1_000_000
        )

    def test_too_large_and_too_small(self) -> None:
        assert "file_too_large" in validate_upload(
            content_type="video/mp4", source_type="mobile", size_bytes=10**12
        )
        assert "file_too_small" in validate_upload(
            content_type="video/mp4", source_type="mobile", size_bytes=10
        )


class TestUploadFlow:
    async def test_create_returns_signed_url(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["upload_url"].startswith("https://fake-storage.local/upload/")
        assert body["raw_ref"].startswith(f"tenant/{tenant_id}/player/")
        assert body["status"] == "created"

    async def test_complete_runs_pipeline(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = (
            await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        ).json()
        r = await client.post(
            f"/v1/videos/{created['ingestion_id']}/complete", headers=_headers(tenant_id)
        )
        assert r.status_code == 200, r.text
        # /complete now runs preprocessing (Step 3) -> status 'processing'.
        assert r.json()["status"] == "processing"

    async def test_get_status(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = (
            await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        ).json()
        r = await client.get(f"/v1/videos/{created['ingestion_id']}", headers=_headers(tenant_id))
        assert r.status_code == 200
        assert r.json()["id"] == created["ingestion_id"]

    async def test_idempotent_create_on_correlation(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        corr = f"corr-{uuid.uuid4().hex}"
        first = await client.post(
            "/v1/videos", headers=_headers(tenant_id, correlation=corr), json=_body()
        )
        second = await client.post(
            "/v1/videos", headers=_headers(tenant_id, correlation=corr), json=_body()
        )
        assert first.status_code == 201 and second.status_code == 201
        # Same correlation -> same ingestion (no duplicate).
        assert first.json()["ingestion_id"] == second.json()["ingestion_id"]


class TestValidationRejection:
    async def test_unsupported_content_type_422(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post(
            "/v1/videos", headers=_headers(tenant_id), json=_body(content_type="image/gif")
        )
        assert r.status_code == 422
        assert "unsupported_content_type" in r.json()["error"]["details"]["reasons"]


class TestEntitlementGate:
    async def test_over_quota_denied_with_reason(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M05-04: over-quota upload denied by the M03 entitlement check."""
        app, client = app_client
        # Flip the fake M03 client to deny.
        app.state.deps.entitlement_client.allowed = False

        r = await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        assert r.status_code == 403
        assert r.json()["error"]["details"]["reason"] == "analysis_quota_exhausted"

    async def test_within_quota_admitted(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        app.state.deps.entitlement_client.allowed = True
        r = await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        assert r.status_code == 201


class TestAuthAndTenancy:
    async def test_unauthenticated_401(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post("/v1/videos", headers={"X-Tenant-ID": str(tenant_id)}, json=_body())
        assert r.status_code == 401

    async def test_cross_tenant_get_404(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        created = (
            await client.post("/v1/videos", headers=_headers(tenant_id), json=_body())
        ).json()
        other_tenant = uuid.uuid4()
        r = await client.get(
            f"/v1/videos/{created['ingestion_id']}", headers=_headers(other_tenant)
        )
        # RLS scopes the read to the other tenant -> row invisible -> 404.
        assert r.status_code == 404
