"""Benchmark worker — the process that consumes ``physics.metrics`` (§8).

Separate process from the FastAPI app: comparison is CPU-bound (NFR-M15-04),
so this is the workload a worker pool runs independently of request/response
traffic.

Run it with::

    python -m benchmark_service.worker
"""

from __future__ import annotations

import asyncio

from benchmark_service.deps import build_deps, shutdown_deps
from benchmark_service.service import (
    CONSUMER_GROUP,
    TOPIC_PHYSICS_METRICS,
    build_benchmark_consumer,
)
from benchmark_service.settings import get_service_settings
from cip_observability import get_logger

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``physics.metrics`` until cancelled. Returns messages processed."""
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_benchmark_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "benchmark.worker.started",
        extra={"topic": TOPIC_PHYSICS_METRICS, "group": group_id},
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_PHYSICS_METRICS, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("benchmark.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
