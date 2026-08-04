"""Biomechanics worker — the process that consumes ``shot.classified`` (§8).

Separate process from the FastAPI app, for the same reason as M06's: bat
detection is the GPU-bound stage, so this is the workload a GPU pool runs and
what queue-depth autoscaling targets (§14, NFR-M07-02). The read API stays up
while the pool scales to zero.

Run it with::

    python -m biomechanics_service.worker
"""

from __future__ import annotations

import asyncio

from biomechanics_service.deps import build_deps, shutdown_deps
from biomechanics_service.service import (
    build_biomechanics_consumer,
    consumer_group_for,
    source_topic_for,
)
from biomechanics_service.settings import get_service_settings
from cip_observability import get_logger

log = get_logger(__name__)


async def run_worker(*, group_id: str | None = None, stop_after: int | None = None) -> int:
    """Consume the trigger topic until cancelled. Returns messages processed.

    The topic and group come from :func:`source_topic_for` /
    :func:`consumer_group_for`, the same functions the consumer is built with.
    Hardcoding them here would let the subscription drift from the consumer —
    the worker would listen on one topic while the consumer expected another,
    and no report would ever be produced.

    ``stop_after`` bounds the loop and ``group_id`` overrides the offsets so a
    test can drive the real consumer against a real broker.
    """
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_biomechanics_consumer(deps, idempotency_store=deps.idempotency_store)
    topic = source_topic_for(deps)
    group = group_id or consumer_group_for(deps)
    processed = 0
    log.info("biomechanics.worker.started", extra={"topic": topic, "group": group})
    try:
        async for envelope in deps.event_bus.consume(topic, group_id=group):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("biomechanics.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
