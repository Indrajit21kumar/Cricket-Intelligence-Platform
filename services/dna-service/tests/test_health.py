"""Unit tests for the reference service's health surface (M01 §9).

Uses TestClient without the lifespan (no infra needed). Real readiness
against live Postgres + Redis + Kafka lives in the integration suite.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from dna_service import __version__
from dna_service.health import router as health_router
from dna_service.health import version_router


def _minimal_app() -> TestClient:
    """Build a FastAPI app carrying only the health + version routers.

    Skips the full lifespan (which would try to open DB + Kafka + Redis)
    because these tests only care about the trivial in-memory responses.
    """
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(version_router)
    return TestClient(app)


def test_liveness_returns_live() -> None:
    client = _minimal_app()
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_liveness_rejects_post() -> None:
    """Only GET is allowed."""
    client = _minimal_app()
    response = client.post("/health/live")
    assert response.status_code == 405


def test_version_returns_current_version() -> None:
    client = _minimal_app()
    response = client.get("/internal/version")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "dna-service"
    assert body["version"] == __version__


def test_unknown_route_returns_404() -> None:
    client = _minimal_app()
    response = client.get("/does-not-exist")
    assert response.status_code == 404
