"""Integration tests for /health/ready (AC-M01-07)."""

from __future__ import annotations

import time

import httpx
import pytest

pytestmark = pytest.mark.integration


class TestHealthReady:
    async def test_returns_200_when_all_deps_up(self, integration_app: httpx.AsyncClient) -> None:
        response = await integration_app.get("/health/ready")
        body = response.json()
        assert response.status_code == 200, f"body: {body}"
        assert body["checks"] == {"postgres": "ok", "redis": "ok", "kafka": "ok"}


class TestHealthLatency:
    async def test_liveness_under_100ms(self, integration_app: httpx.AsyncClient) -> None:
        await integration_app.get("/health/live")
        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            resp = await integration_app.get("/health/live")
            latencies.append(time.perf_counter() - start)
            assert resp.status_code == 200
        latencies.sort()
        assert latencies[len(latencies) // 2] * 1000 < 100
