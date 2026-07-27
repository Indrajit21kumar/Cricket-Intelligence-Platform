"""Physics worker — the process that consumes ``biomechanics.metrics`` (§10).

Separate process from the FastAPI app: the physics compute is the CPU-bound
stage, so this is the workload a CPU pool runs and what queue-depth autoscaling
targets (§16, NFR-M11-01). The read API stays up while the pool scales.

Run it with::

    python -m physics_service.worker
"""

from __future__ import annotations

import asyncio

from cip_observability import get_logger
from physics_service.deps import build_deps, shutdown_deps
from physics_service.service import (
    CONSUMER_GROUP,
    TOPIC_BIOMECHANICS_METRICS,
    build_physics_consumer,
)
from physics_service.settings import get_service_settings

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``biomechanics.metrics`` until cancelled. Returns messages processed.

    ``stop_after`` bounds the loop and ``group_id`` isolates the offsets so a
    test can drive the real consumer against a real broker; production leaves
    both at their defaults.
    """
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_physics_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "physics.worker.started",
        extra={"topic": TOPIC_BIOMECHANICS_METRICS, "group": group_id},
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_BIOMECHANICS_METRICS, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("physics.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
