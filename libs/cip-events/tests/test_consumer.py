"""Unit tests for :class:`IdempotentConsumer` — the dedup + retry + DLQ core.

Uses a fake in-memory :class:`EventBus` and the in-memory idempotency store,
so the state machine can be exercised without a running broker. Behavioural
end-to-end verification with real Kafka + Redis lives in the integration
suite.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from cip_events.consumer import IdempotentConsumer
from cip_events.envelope import EventEnvelope
from cip_events.idempotency import InMemoryIdempotencyStore
from cip_events.retry import RetryPolicy


class FakeBus:
    """Records everything published — for asserting DLQ routing."""

    def __init__(self) -> None:
        self.published: list[tuple[str, EventEnvelope]] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        self.published.append((topic, envelope))

    async def consume(  # type: ignore[misc]  # pragma: no cover — not driven in unit tests
        self, topic: str, group_id: str
    ) -> AsyncIterator[EventEnvelope]:
        raise NotImplementedError
        yield  # unreachable, satisfies AsyncIterator return type


def _env(idem: str = "idem-1", corr: str = "corr-1") -> EventEnvelope:
    return EventEnvelope(
        correlation_id=corr,
        tenant_id=uuid.uuid4(),
        schema_version="1.0.0",
        idempotency_key=idem,
    )


def _fast_retry(max_attempts: int = 3) -> RetryPolicy:
    """Retry policy with zero delay — tests should run in ms, not seconds."""
    return RetryPolicy(
        max_attempts=max_attempts,
        initial_delay_seconds=0.0,
        backoff_factor=1.0,
        max_delay_seconds=0.0,
    )


class TestHappyPath:
    async def test_handler_invoked_once_on_success(self) -> None:
        invocations: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            invocations.append(env)

        consumer = IdempotentConsumer(
            bus=FakeBus(),
            idempotency_store=InMemoryIdempotencyStore(),
            handler=handler,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(),
        )
        envelope = _env()
        result = await consumer.process_one(envelope)

        assert result.handler_invoked is True
        assert result.success is True
        assert result.attempts == 1
        assert invocations == [envelope]


class TestDeduplication:
    """AC-M01-05 half A: replay same event N times → 1 handler invocation."""

    async def test_replay_same_key_only_invokes_once(self) -> None:
        invocations: list[EventEnvelope] = []

        async def handler(env: EventEnvelope) -> None:
            invocations.append(env)

        consumer = IdempotentConsumer(
            bus=FakeBus(),
            idempotency_store=InMemoryIdempotencyStore(),
            handler=handler,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(),
        )
        envelope = _env(idem="same-key")

        for _ in range(5):
            await consumer.process_one(envelope)

        assert len(invocations) == 1

    async def test_replayed_message_reports_duplicate(self) -> None:
        async def handler(env: EventEnvelope) -> None:
            pass

        consumer = IdempotentConsumer(
            bus=FakeBus(),
            idempotency_store=InMemoryIdempotencyStore(),
            handler=handler,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(),
        )
        envelope = _env(idem="dup-key")

        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True

        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False
        assert second.success is True
        assert second.attempts == 0


class TestRetryAndDLQ:
    """AC-M01-05 half B: poisoned handler → message lands in DLQ."""

    async def test_retries_then_dlq_on_persistent_failure(self) -> None:
        attempts: list[int] = []

        async def always_fails(env: EventEnvelope) -> None:
            attempts.append(len(attempts) + 1)
            raise RuntimeError("boom")

        bus = FakeBus()
        consumer = IdempotentConsumer(
            bus=bus,
            idempotency_store=InMemoryIdempotencyStore(),
            handler=always_fails,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(max_attempts=3),
        )
        envelope = _env()

        result = await consumer.process_one(envelope)

        assert result.success is False
        assert result.attempts == 3
        assert bus.published == [("src.dlq", envelope)]

    async def test_succeeds_on_second_attempt(self) -> None:
        call_count = 0

        async def flaky(env: EventEnvelope) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient")

        bus = FakeBus()
        consumer = IdempotentConsumer(
            bus=bus,
            idempotency_store=InMemoryIdempotencyStore(),
            handler=flaky,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(max_attempts=3),
        )

        result = await consumer.process_one(_env())

        assert result.success is True
        assert result.attempts == 2
        assert bus.published == []  # not DLQ'd


class TestContextScoping:
    """The consumer MUST bind correlation_id + tenant_id for the handler."""

    async def test_handler_sees_bound_context(self) -> None:
        seen: dict[str, object] = {}

        async def handler(env: EventEnvelope) -> None:
            from cip_core import get_correlation_id, get_tenant_id

            seen["correlation_id"] = get_correlation_id()
            seen["tenant_id"] = get_tenant_id()

        envelope = _env(corr="corr-abc")
        consumer = IdempotentConsumer(
            bus=FakeBus(),
            idempotency_store=InMemoryIdempotencyStore(),
            handler=handler,
            source_topic="src",
            dlq_topic="src.dlq",
            group_id="g1",
            retry_policy=_fast_retry(),
        )
        await consumer.process_one(envelope)

        assert seen["correlation_id"] == "corr-abc"
        assert seen["tenant_id"] == envelope.tenant_id
