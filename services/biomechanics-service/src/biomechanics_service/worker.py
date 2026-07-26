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
    CONSUMER_GROUP,
    TOPIC_SHOT_CLASSIFIED,
    build_biomechanics_consumer,
)
from biomechanics_service.settings import get_service_settings
from cip_observability import get_logger

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``video.normalized`` until cancelled. Returns messages processed.

    ``stop_after`` bounds the loop and ``group_id`` isolates the offsets so a
    test can drive the real consumer against a real broker; production leaves
    both at their defaults.
    """
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_biomechanics_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "biomechanics.worker.started", extra={"topic": TOPIC_SHOT_CLASSIFIED, "group": group_id}
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_SHOT_CLASSIFIED, group_id=group_id):
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
