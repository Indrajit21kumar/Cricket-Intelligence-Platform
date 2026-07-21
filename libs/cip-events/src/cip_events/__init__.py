"""cip-events — Kafka-wire event bus, idempotent consumer, DLQ routing.

Public API stabilised in M01 Step 5. Every CIP topic message follows the
:class:`EventEnvelope` contract; every consumer wraps its handler in
:class:`IdempotentConsumer` so duplicates and failures are handled
uniformly (Book 2 §4.2).
"""

from __future__ import annotations

from cip_events.bus import EventBus
from cip_events.consumer import ConsumerResult, Handler, IdempotentConsumer
from cip_events.envelope import EventEnvelope
from cip_events.idempotency import (
    DEFAULT_TTL_SECONDS,
    IdempotencyStore,
    InMemoryIdempotencyStore,
    RedisIdempotencyStore,
)
from cip_events.kafka import KafkaEventBus
from cip_events.provenance import Provenance
from cip_events.retry import RetryPolicy

__version__ = "0.1.0"

__all__ = [
    "DEFAULT_TTL_SECONDS",
    "ConsumerResult",
    "EventBus",
    "EventEnvelope",
    "Handler",
    "IdempotencyStore",
    "IdempotentConsumer",
    "InMemoryIdempotencyStore",
    "KafkaEventBus",
    "Provenance",
    "RedisIdempotencyStore",
    "RetryPolicy",
    "__version__",
]
