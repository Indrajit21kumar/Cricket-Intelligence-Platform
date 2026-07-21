"""Idempotent consumer with retry + DLQ routing.

The consumer sits between an :class:`EventBus` (broker) and the application
handler. For each incoming envelope it:

1. **Deduplicates** via :class:`IdempotencyStore` — if the ``idempotency_key``
   has been seen before, the message is ACK'd without invoking the handler.
2. **Invokes** the handler under a :func:`cip_core.correlation_scope` +
   :func:`cip_core.tenant_scope` so logs, spans, and DB queries automatically
   pick up the envelope's identifiers.
3. **On failure**, retries per :class:`RetryPolicy` (exponential backoff).
4. **After max_attempts**, routes the envelope to the DLQ topic and ACKs
   the original — the message must never silently disappear.

This is the shape every stage in the intelligence pipeline uses. Domain
handlers stay pure business logic; the invariants above live here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cip_core import correlation_scope, tenant_scope

from cip_events.bus import EventBus
from cip_events.envelope import EventEnvelope
from cip_events.idempotency import IdempotencyStore
from cip_events.retry import RetryPolicy

log = logging.getLogger(__name__)

Handler = Callable[[EventEnvelope], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ConsumerResult:
    """Outcome of a single message pass — used by tests to assert behaviour."""

    #: The envelope that was consumed.
    envelope: EventEnvelope
    #: Was the handler invoked (False on duplicate)?
    handler_invoked: bool
    #: True if handled successfully (or duplicated); False if routed to DLQ.
    success: bool
    #: Number of handler attempts made (1 on success first-try, up to
    #: max_attempts on DLQ, 0 on duplicate).
    attempts: int


class IdempotentConsumer:
    """Dedupe + retry + DLQ wrapper around a handler."""

    def __init__(
        self,
        *,
        bus: EventBus,
        idempotency_store: IdempotencyStore,
        handler: Handler,
        source_topic: str,
        dlq_topic: str,
        group_id: str,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._bus = bus
        self._store = idempotency_store
        self._handler = handler
        self._source_topic = source_topic
        self._dlq_topic = dlq_topic
        self._group_id = group_id
        self._retry = retry_policy or RetryPolicy()

    async def process_one(self, envelope: EventEnvelope) -> ConsumerResult:
        """Process a single envelope — dedup, invoke, retry, DLQ.

        Exposed as its own method so tests can drive the state machine
        without spinning up a real broker consumer loop. Production callers
        use :meth:`run` (added when the reference-service ships in Step 6).
        """
        claimed = await self._store.claim(envelope.idempotency_key)
        if not claimed:
            log.info(
                "cip.events.duplicate",
                extra={
                    "topic": self._source_topic,
                    "idempotency_key": envelope.idempotency_key,
                    "correlation_id": envelope.correlation_id,
                },
            )
            return ConsumerResult(
                envelope=envelope,
                handler_invoked=False,
                success=True,
                attempts=0,
            )

        attempt = 0
        last_exc: BaseException | None = None
        with (
            correlation_scope(envelope.correlation_id),
            tenant_scope(envelope.tenant_id),
        ):
            while attempt < self._retry.max_attempts:
                attempt += 1
                delay = self._retry.delay_for_attempt(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                try:
                    await self._handler(envelope)
                    return ConsumerResult(
                        envelope=envelope,
                        handler_invoked=True,
                        success=True,
                        attempts=attempt,
                    )
                except Exception as exc:
                    last_exc = exc
                    log.warning(
                        "cip.events.handler_failed",
                        extra={
                            "topic": self._source_topic,
                            "attempt": attempt,
                            "max_attempts": self._retry.max_attempts,
                            "correlation_id": envelope.correlation_id,
                            "error": repr(exc),
                        },
                    )
                    if not self._retry.should_retry(attempt):
                        break

        # All retries exhausted — route to DLQ (never silently drop).
        await self._bus.publish(self._dlq_topic, envelope)
        log.error(
            "cip.events.dlq_routed",
            extra={
                "source_topic": self._source_topic,
                "dlq_topic": self._dlq_topic,
                "correlation_id": envelope.correlation_id,
                "attempts": attempt,
                "last_error": repr(last_exc),
            },
        )
        return ConsumerResult(
            envelope=envelope,
            handler_invoked=True,
            success=False,
            attempts=attempt,
        )
