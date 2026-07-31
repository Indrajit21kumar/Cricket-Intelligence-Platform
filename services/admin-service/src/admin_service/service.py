"""Warehouse ingestion orchestration (M20 Step 1, FR-M20-03/04).

The warehouse is fed by consuming the platform's REAL event topics — the
same topics every producing service already publishes — so Step 4's
revenue/usage analytics report on what actually happened, not a fabricated
substitute. One :class:`IdempotentConsumer` per ingested topic, all sharing
one consumer group (offsets are tracked per topic-partition regardless) and
one warehouse-specific DLQ.
"""

from __future__ import annotations

from admin_service.deps import Deps
from admin_service.domain.ingest import (
    ALL_INGESTED_TOPICS,
    WAREHOUSE_CONSUMER_GROUP,
    WAREHOUSE_DLQ_TOPIC,
)
from admin_service.domain.warehouse_repo import ingest_envelope
from cip_data.engine import admin_session
from cip_events import EventEnvelope, IdempotencyStore, IdempotentConsumer


async def handle_warehouse_event(deps: Deps, topic: str, envelope: EventEnvelope) -> None:
    """Consumer handler: ingest one envelope into its fact table."""
    async with admin_session(deps.session_factory) as session:
        await ingest_envelope(session, topic=topic, envelope=envelope)


def build_warehouse_consumer(
    deps: Deps, *, topic: str, idempotency_store: IdempotencyStore
) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over one ingested topic -> its fact table."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_warehouse_event(deps, topic, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=topic,
        dlq_topic=WAREHOUSE_DLQ_TOPIC,
        group_id=WAREHOUSE_CONSUMER_GROUP,
    )


def build_all_warehouse_consumers(
    deps: Deps,
    *,
    idempotency_store: IdempotencyStore,
    topics: tuple[str, ...] = ALL_INGESTED_TOPICS,
) -> dict[str, IdempotentConsumer]:
    return {
        topic: build_warehouse_consumer(deps, topic=topic, idempotency_store=idempotency_store)
        for topic in topics
    }
