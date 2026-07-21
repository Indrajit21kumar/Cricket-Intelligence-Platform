"""Integration tests for :class:`KafkaEventBus` (needs local Redpanda).

Uses unique topic names per test (uuid suffix) so tests don't collide even
though Kafka topics persist across the docker-compose lifetime.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from cip_events.envelope import EventEnvelope
from cip_events.kafka import KafkaEventBus

pytestmark = pytest.mark.integration

DEFAULT_BOOTSTRAP = "localhost:9092"


def _bootstrap() -> str:
    return os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP)


@pytest_asyncio.fixture
async def bus() -> KafkaEventBus:
    b = KafkaEventBus(bootstrap_servers=_bootstrap())
    await b.start()
    yield b
    await b.stop()


def _env(idem_suffix: str = "1") -> EventEnvelope:
    return EventEnvelope(
        correlation_id=f"corr-{idem_suffix}",
        tenant_id=uuid.uuid4(),
        schema_version="1.0.0",
        idempotency_key=f"idem-{idem_suffix}",
        payload={"greeting": "hello"},
    )


async def _consume_one(
    bus: KafkaEventBus, topic: str, group_id: str, timeout: float = 10.0
) -> EventEnvelope:
    """Fetch a single envelope from ``topic`` or fail after ``timeout``."""

    async def _next() -> EventEnvelope:
        async for env in bus.consume(topic, group_id):
            return env
        raise RuntimeError("consumer iterator exited without yielding")

    return await asyncio.wait_for(_next(), timeout=timeout)


class TestKafkaRoundTrip:
    async def test_publish_then_consume(self, bus: KafkaEventBus) -> None:
        topic = f"test.roundtrip.{uuid.uuid4().hex[:8]}"
        original = _env()

        await bus.publish(topic, original)
        received = await _consume_one(bus, topic, group_id=f"g-{uuid.uuid4().hex[:8]}")

        assert received == original

    async def test_partitions_by_tenant(self, bus: KafkaEventBus) -> None:
        """Same tenant → same key → same partition (ordering preserved)."""
        topic = f"test.partkey.{uuid.uuid4().hex[:8]}"
        tid = uuid.uuid4()
        envelopes = [
            EventEnvelope(
                correlation_id=f"c-{i}",
                tenant_id=tid,
                schema_version="1.0.0",
                idempotency_key=f"k-{i}",
                payload={"seq": i},
            )
            for i in range(3)
        ]
        for env in envelopes:
            await bus.publish(topic, env)

        group = f"g-{uuid.uuid4().hex[:8]}"
        received: list[EventEnvelope] = []

        async def _collect() -> None:
            async for env in bus.consume(topic, group):
                received.append(env)
                if len(received) == 3:
                    return

        await asyncio.wait_for(_collect(), timeout=10.0)

        # Order is guaranteed per partition; since all three share the same
        # tenant key they land on the same partition and arrive in order.
        assert [e.payload["seq"] for e in received] == [0, 1, 2]
