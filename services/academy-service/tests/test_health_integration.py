"""Integration tests for /health/ready (AC-M01-07).

Runs against the fully-wired app with real Postgres + Redis + Kafka up
(from docker-compose locally, service containers + Redpanda step in CI).
"""

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
        assert body["status"] == "ready"
        assert body["checks"] == {"postgres": "ok", "redis": "ok", "kafka": "ok"}


class TestHealthLatency:
    """AC-M01-07: health endpoints respond in <100ms under normal load."""

    async def test_liveness_under_100ms(self, integration_app: httpx.AsyncClient) -> None:
        # Warm connection (first call may pay TCP handshake).
        await integration_app.get("/health/live")
        # Take the median of 5 to smooth transient spikes on shared runners.
        latencies = []
        for _ in range(5):
            start = time.perf_counter()
            resp = await integration_app.get("/health/live")
            latencies.append(time.perf_counter() - start)
            assert resp.status_code == 200
        latencies.sort()
        median_ms = latencies[len(latencies) // 2] * 1000
        assert median_ms < 100, f"liveness p50 was {median_ms:.1f}ms (>100ms)"
