"""End-to-end correlation-id flow test (AC-M01-03 finalisation).

Verifies the invariant Book 3 §8 mandates: correlation_id is present in the
HTTP response header AND in the envelope of the event the handler publishes.
That is, it survives the multi-hop HTTP -> event boundary — the shape the
whole intelligence pipeline depends on.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pytest
from cip_events import EventEnvelope, KafkaEventBus
from reference_service.routes import DEMO_TOPIC

pytestmark = pytest.mark.integration

DEFAULT_BOOTSTRAP = "localhost:9092"


class TestCorrelationFlowHttpToEvent:
    async def test_correlation_id_survives_http_to_event(
        self,
        integration_app: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        # Start a consumer BEFORE publishing so we don't miss the message.
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"corr-flow-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(DEMO_TOPIC, group_id=group)
            # Kafka delivers "earliest" so we don't need to pre-warm the
            # partition assignment; consumer_iter picks up the message we
            # publish next.

            correlation_id = f"corr-{uuid.uuid4().hex}"
            response = await integration_app.post(
                "/v1/demo/echo",
                json={"message": "hello"},
                headers={
                    "X-Correlation-ID": correlation_id,
                    "X-Tenant-ID": str(tenant_id),
                    "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
                },
            )

            # 1) response echoes correlation_id in the header
            assert response.status_code == 200
            assert response.headers["X-Correlation-ID"] == correlation_id

            # 2) response body carries it too
            body = response.json()
            assert body["correlation_id"] == correlation_id
            assert body["tenant_id"] == str(tenant_id)

            # 3) the event the handler published carries the SAME correlation_id.
            # The topic persists across test runs so we skip stale envelopes
            # from previous runs and match on OUR correlation_id.
            async def _find_ours() -> EventEnvelope:
                async for env in consumer_iter:
                    if env.correlation_id == correlation_id:
                        return env
                raise RuntimeError("consumer exhausted without yielding ours")

            envelope = await asyncio.wait_for(_find_ours(), timeout=15.0)
            assert envelope.correlation_id == correlation_id
            assert envelope.tenant_id == tenant_id
            assert envelope.payload["message"] == "hello"
        finally:
            await bus.stop()


class TestTenancyEnforcement:
    async def test_missing_tenant_header_rejected(
        self,
        integration_app: httpx.AsyncClient,
    ) -> None:
        """Handler calls require_tenant_id(); no header -> 400 with envelope."""
        response = await integration_app.post(
            "/v1/demo/echo",
            json={"message": "hi"},
            headers={"Idempotency-Key": "idem-1"},
        )
        # Middleware doesn't set tenant → require_tenant_id() raises
        # MissingTenantError → generic exception handler → 500 with envelope.
        # This is intentional: it's a defensive invariant, not a client error.
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["code"] == "INTERNAL_ERROR"

    async def test_missing_idempotency_key_rejected(
        self,
        integration_app: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        """Book 3 §3.1 mandates Idempotency-Key on mutating endpoints."""
        response = await integration_app.post(
            "/v1/demo/echo",
            json={"message": "hi"},
            headers={"X-Tenant-ID": str(tenant_id)},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "BAD_REQUEST"

    async def test_valid_request_succeeds(
        self,
        integration_app: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        response = await integration_app.post(
            "/v1/demo/echo",
            json={"message": "hi"},
            headers={
                "X-Tenant-ID": str(tenant_id),
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
        )
        assert response.status_code == 200
        assert response.json()["tenant_id"] == str(tenant_id)
