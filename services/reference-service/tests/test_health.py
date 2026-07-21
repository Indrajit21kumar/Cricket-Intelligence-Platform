"""Unit tests for the reference service's health surface (M01 Step 1).

Book 3 Ch. 6 §6.1 requires typical/boundary/degenerate fixtures on every unit;
the health endpoints are simple enough that the three cases collapse to
'present', 'shape correct', and 'method not allowed'.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from reference_service import __version__
from reference_service.main import app

client = TestClient(app)


def test_liveness_returns_live() -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_readiness_returns_ready() -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


def test_version_returns_current_version() -> None:
    response = client.get("/internal/version")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "reference-service"
    assert body["version"] == __version__


def test_liveness_rejects_post() -> None:
    """Boundary: only GET is allowed on health endpoints."""
    response = client.post("/health/live")
    assert response.status_code == 405


def test_unknown_route_returns_404() -> None:
    """Degenerate: unknown routes surface a 404, not a crash."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404
