"""Unit tests for the report service's health surface (M01 §9)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from report_service import __version__
from report_service.health import router as health_router
from report_service.health import version_router


def _minimal_app() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(health_router)
    app.include_router(version_router)
    return TestClient(app)


def test_liveness_returns_live() -> None:
    response = _minimal_app().get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "live"}


def test_liveness_rejects_post() -> None:
    assert _minimal_app().post("/health/live").status_code == 405


def test_version_returns_current_version() -> None:
    body = _minimal_app().get("/internal/version").json()
    assert body["service"] == "report-service"
    assert body["version"] == __version__


def test_unknown_route_returns_404() -> None:
    assert _minimal_app().get("/does-not-exist").status_code == 404
