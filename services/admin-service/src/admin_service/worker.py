"""Warehouse ingestion worker — the process that feeds the warehouse (M20 Step 1).

Unlike every other CIP worker (which consumes exactly one topic), this one
consumes the whole set of :data:`~admin_service.domain.ingest.ALL_INGESTED_TOPICS`
concurrently — one consume loop per topic, gathered together. It is
deliberately a separate process from the FastAPI app, same as every other
CIP worker: the API serves reads (Step 4 onward), this is what feeds them.

Run it with::

    python -m admin_service.worker
"""

from __future__ import annotations

import asyncio

from admin_service.deps import Deps, build_deps, shutdown_deps
from admin_service.domain.ingest import ALL_INGESTED_TOPICS, WAREHOUSE_CONSUMER_GROUP
from admin_service.service import build_warehouse_consumer
from admin_service.settings import get_service_settings
from cip_events import IdempotentConsumer
from cip_observability import get_logger

log = get_logger(__name__)


async def _consume_topic(
    deps: Deps,
    consumer: IdempotentConsumer,
    *,
    topic: str,
    group_id: str,
    stop_after: int | None,
) -> int:
    processed = 0
    async for envelope in deps.event_bus.consume(topic, group_id=group_id):
        await consumer.process_one(envelope)
        processed += 1
        if stop_after is not None and processed >= stop_after:
            break
    return processed


async def run_worker(
    *,
    group_id: str = WAREHOUSE_CONSUMER_GROUP,
    stop_after: int | None = None,
    topics: tuple[str, ...] = ALL_INGESTED_TOPICS,
) -> int:
    """Consume every ingested topic until cancelled. Returns total messages processed.

    ``stop_after`` bounds EACH topic's loop and ``group_id`` isolates the
    offsets, so a test can run the real consumer against a real broker
    without inheriting the shared group's position; production leaves both
    at their defaults.
    """
    settings = get_service_settings()
    deps = await build_deps(settings)
    log.info("admin.warehouse_worker.started", extra={"topics": topics, "group": group_id})
    try:
        results = await asyncio.gather(
            *(
                _consume_topic(
                    deps,
                    build_warehouse_consumer(
                        deps, topic=topic, idempotency_store=deps.idempotency_store
                    ),
                    topic=topic,
                    group_id=group_id,
                    stop_after=stop_after,
                )
                for topic in topics
            )
        )
        return sum(results)
    finally:
        log.info("admin.warehouse_worker.stopped")
        await shutdown_deps(deps)


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
