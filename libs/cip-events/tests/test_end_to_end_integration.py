"""End-to-end integration test for AC-M01-05.

Exercises the whole cip-events stack — real Redpanda + real Redis — via the
IdempotentConsumer. Proves:

1. Same event delivered 5x -> handler invoked exactly once.
2. Handler that always fails -> message lands in the DLQ topic.

This is the acceptance test M01 §15 gates on.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio
from cip_events.consumer import IdempotentConsumer
from cip_events.envelope import EventEnvelope
from cip_events.idempotency import RedisIdempotencyStore
from cip_events.kafka import KafkaEventBus
from cip_events.retry import RetryPolicy

pytestmark = pytest.mark.integration


DEFAULT_BOOTSTRAP = "localhost:9092"
DEFAULT_REDIS = "redis://localhost:6379/0"


@pytest_asyncio.fixture
async def bus() -> KafkaEventBus:
    b = KafkaEventBus(bootstrap_servers=os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
    await b.start()
    yield b
    await b.stop()


@pytest_asyncio.fixture
async def redis_store() -> RedisIdempotencyStore:
    s = RedisIdempotencyStore(os.environ.get("CIP_REDIS_URL", DEFAULT_REDIS))
    yield s
    await s.close()


def _env(idem: str, corr: str = "corr-e2e") -> EventEnvelope:
    return EventEnvelope(
        correlation_id=corr,
        tenant_id=uuid.uuid4(),
        schema_version="1.0.0",
        idempotency_key=idem,
        payload={"marker": idem},
    )


def _fast_retry(max_attempts: int = 3) -> RetryPolicy:
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_delay_seconds=0.0,
        backoff_factor=1.0,
        max_delay_seconds=0.0,
    )


class TestAcceptanceCriterion05:
    async def test_duplicate_delivery_causes_no_duplicate_effect(
        self, bus: KafkaEventBus, redis_store: RedisIdempotencyStore
    ) -> None:
        invocations: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            invocations.append(env)

        consumer = IdempotentConsumer(
            bus=bus,
            idempotency_store=redis_store,
            handler=handler,
            source_topic=f"src.{uuid.uuid4().hex[:8]}",
            dlq_topic=f"dlq.{uuid.uuid4().hex[:8]}",
            group_id=f"g-{uuid.uuid4().hex[:8]}",
            retry_policy=_fast_retry(),
        )

        envelope = _env(idem=f"e2e-dup-{uuid.uuid4().hex[:8]}")
        # Simulate "same event delivered 5x" — the AC-M01-05 wording.
        for _ in range(5):
            await consumer.process_one(envelope)

        assert len(invocations) == 1

    async def test_poisoned_handler_lands_in_dlq(
        self, bus: KafkaEventBus, redis_store: RedisIdempotencyStore
    ) -> None:
        dlq_topic = f"dlq.{uuid.uuid4().hex[:8]}"
        source = f"src.{uuid.uuid4().hex[:8]}"

        async def always_fails(env: EventEnvelope) -> None:
            raise RuntimeError("handler poisoned")

        consumer = IdempotentConsumer(
            bus=bus,
            idempotency_store=redis_store,
            handler=always_fails,
            source_topic=source,
            dlq_topic=dlq_topic,
            group_id=f"g-{uuid.uuid4().hex[:8]}",
            retry_policy=_fast_retry(max_attempts=3),
        )

        envelope = _env(idem=f"e2e-dlq-{uuid.uuid4().hex[:8]}")
        result = await consumer.process_one(envelope)

        assert result.success is False
        assert result.attempts == 3

        # Confirm the envelope was actually published to the DLQ topic.
        async def _read_dlq() -> EventEnvelope:
            async for env in bus.consume(dlq_topic, group_id=f"reader-{uuid.uuid4().hex[:8]}"):
                return env
            raise RuntimeError("dlq consumer exited")

        dlq_envelope = await asyncio.wait_for(_read_dlq(), timeout=10.0)
        assert dlq_envelope == envelope
