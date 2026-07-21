"""Event bus abstraction — the seam that hides the concrete broker.

Callers depend on :class:`EventBus`; the Kafka implementation is in
:mod:`cip_events.kafka`. Cloud managed alternatives (GCP Pub/Sub, AWS SNS)
plug in the same way without touching consumer code.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from cip_events.envelope import EventEnvelope


@runtime_checkable
class EventBus(Protocol):
    """Minimal contract every broker implementation exposes."""

    async def start(self) -> None:
        """Open connections / handshake with the broker."""
        ...

    async def stop(self) -> None:
        """Close connections + flush pending writes."""
        ...

    async def publish(self, topic: str, envelope: EventEnvelope) -> None:
        """Publish ``envelope`` to ``topic``. Blocks until the broker ACKs."""
        ...

    def consume(self, topic: str, group_id: str) -> AsyncIterator[EventEnvelope]:
        """Yield envelopes from ``topic`` for the consumer group.

        Iteration ends when :meth:`stop` is called on the bus.
        """
        ...
