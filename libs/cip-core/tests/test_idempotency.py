"""Tests for :mod:`cip_core.idempotency`."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from cip_core.errors import CIPErrorCode
from cip_core.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_KEY_LENGTH,
    idempotency_key,
    require_idempotency_key,
)
from cip_core.middleware import install


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    install(app)

    @app.post("/optional")
    def optional_endpoint(
        key: str | None = Depends(idempotency_key),
    ) -> dict[str, str | None]:
        return {"key": key}

    @app.post("/required")
    def required_endpoint(
        key: str = Depends(require_idempotency_key),
    ) -> dict[str, str]:
        return {"key": key}

    return TestClient(app)


class TestOptionalIdempotencyKey:
    def test_absent_returns_none(self, client: TestClient) -> None:
        response = client.post("/optional")
        assert response.status_code == 200
        assert response.json() == {"key": None}

    def test_valid_returns_key(self, client: TestClient) -> None:
        response = client.post("/optional", headers={IDEMPOTENCY_HEADER: "abc-123"})
        assert response.status_code == 200
        assert response.json() == {"key": "abc-123"}

    def test_empty_string_is_400(self, client: TestClient) -> None:
        response = client.post("/optional", headers={IDEMPOTENCY_HEADER: ""})
        assert response.status_code == 400
        assert response.json()["error"]["code"] == CIPErrorCode.BAD_REQUEST.value

    def test_too_long_is_400(self, client: TestClient) -> None:
        oversized = "x" * (MAX_KEY_LENGTH + 1)
        response = client.post("/optional", headers={IDEMPOTENCY_HEADER: oversized})
        assert response.status_code == 400
        details = response.json()["error"]["details"]
        assert details == {"max_length": MAX_KEY_LENGTH, "actual": MAX_KEY_LENGTH + 1}


class TestRequiredIdempotencyKey:
    def test_absent_is_400(self, client: TestClient) -> None:
        response = client.post("/required")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == CIPErrorCode.BAD_REQUEST.value

    def test_valid_returns_key(self, client: TestClient) -> None:
        response = client.post("/required", headers={IDEMPOTENCY_HEADER: "k1"})
        assert response.status_code == 200
        assert response.json() == {"key": "k1"}

    def test_boundary_max_length_ok(self, client: TestClient) -> None:
        maxed = "y" * MAX_KEY_LENGTH
        response = client.post("/required", headers={IDEMPOTENCY_HEADER: maxed})
        assert response.status_code == 200
        assert response.json() == {"key": maxed}
