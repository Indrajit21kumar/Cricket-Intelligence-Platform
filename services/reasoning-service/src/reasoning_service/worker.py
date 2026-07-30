"""Reasoning worker — the process that consumes ``physics.metrics`` (§9).

Separate process from the FastAPI app: the pipeline is CPU-bound, so this is the
workload a CPU pool runs and what queue-depth autoscaling targets (NFR-M13-05).

Run it with::

    python -m reasoning_service.worker
"""

from __future__ import annotations

import asyncio

from cip_observability import get_logger
from reasoning_service.deps import build_deps, shutdown_deps
from reasoning_service.service import (
    CONSUMER_GROUP,
    TOPIC_PHYSICS_METRICS,
    build_reasoning_consumer,
)
from reasoning_service.settings import get_service_settings

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``physics.metrics`` until cancelled. Returns messages processed."""
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_reasoning_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "reasoning.worker.started",
        extra={"topic": TOPIC_PHYSICS_METRICS, "group": group_id},
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_PHYSICS_METRICS, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("reasoning.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
