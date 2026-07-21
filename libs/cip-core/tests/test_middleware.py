"""Tests for :mod:`cip_core.middleware`.

Verifies:
- Incoming X-Correlation-ID is honoured; missing header generates a fresh id.
- Response echoes the correlation id back.
- Valid X-Tenant-ID binds the tenant context for the handler.
- Missing tenant header does NOT fail middleware (only tenant-scoped code fails).
- Malformed tenant UUID → 400 with envelope.
- CIPError raised in a handler → correct HTTP status + envelope body.
- Uncaught exception in a handler → 500 with envelope; internals not leaked.

These are pure unit tests: no DB, no network, no docker.
"""

from __future__ import annotations

import uuid

import pytest
from cip_core.context import get_tenant_id
from cip_core.errors import CIPErrorCode, NotFound
from cip_core.middleware import (
    CORRELATION_HEADER,
    TENANT_HEADER,
    install,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    install(app)

    @app.get("/ok")
    def ok() -> dict[str, str]:
        return {"tenant": str(get_tenant_id())}

    @app.get("/notfound")
    def not_found() -> None:
        raise NotFound("player-123 not registered")

    @app.get("/kaboom")
    def kaboom() -> None:
        raise ValueError("secret database URL leaked into message")

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # raise_server_exceptions=False lets the app's exception handler produce
    # a 500 response we can inspect, matching real HTTP behaviour. Without it,
    # Starlette's TestClient re-raises unhandled exceptions to the test.
    return TestClient(app, raise_server_exceptions=False)


class TestCorrelationHeader:
    def test_honours_incoming_header(self, client: TestClient) -> None:
        response = client.get("/ok", headers={CORRELATION_HEADER: "my-corr-id"})
        assert response.status_code == 200
        assert response.headers[CORRELATION_HEADER] == "my-corr-id"

    def test_generates_when_absent(self, client: TestClient) -> None:
        response = client.get("/ok")
        assert response.status_code == 200
        cid = response.headers[CORRELATION_HEADER]
        assert cid
        assert len(cid) == 32

    def test_correlation_in_error_response(self, client: TestClient) -> None:
        response = client.get("/notfound", headers={CORRELATION_HEADER: "trace-me"})
        assert response.headers[CORRELATION_HEADER] == "trace-me"
        assert response.json()["error"]["request_id"] == "trace-me"


class TestTenantHeader:
    def test_valid_uuid_binds_context(self, client: TestClient) -> None:
        tid = uuid.uuid4()
        response = client.get("/ok", headers={TENANT_HEADER: str(tid)})
        assert response.status_code == 200
        assert response.json() == {"tenant": str(tid)}

    def test_absent_tenant_is_not_an_error(self, client: TestClient) -> None:
        """The middleware does not itself enforce tenancy. Enforcement is at
        require_tenant_id() call sites, so bare / unauthenticated / infra
        routes remain reachable."""
        response = client.get("/ok")
        assert response.status_code == 200
        assert response.json() == {"tenant": "None"}

    def test_malformed_tenant_returns_400_envelope(self, client: TestClient) -> None:
        response = client.get("/ok", headers={TENANT_HEADER: "not-a-uuid"})
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["code"] == CIPErrorCode.BAD_REQUEST.value
        assert TENANT_HEADER in body["error"]["message"]


class TestExceptionHandlers:
    def test_cip_error_becomes_envelope(self, client: TestClient) -> None:
        response = client.get("/notfound")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == CIPErrorCode.NOT_FOUND.value
        assert body["error"]["message"] == "player-123 not registered"
        assert body["error"]["request_id"]

    def test_uncaught_exception_returns_generic_500(self, client: TestClient) -> None:
        response = client.get("/kaboom")
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == CIPErrorCode.INTERNAL_ERROR.value
        # Message MUST NOT leak the original exception text — that could
        # expose secrets, stack pointers, or internal state.
        assert "secret database URL" not in body["error"]["message"]
        assert body["error"]["message"] == "Internal server error"
