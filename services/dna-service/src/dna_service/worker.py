"""DNA worker — the process that consumes ``report.ready`` (§8).

Separate process from the FastAPI app: the update is CPU-bound
(NFR-M16-05), so this is the workload a worker pool runs independently of
request/response traffic.

Run it with::

    python -m dna_service.worker
"""

from __future__ import annotations

import asyncio

from cip_observability import get_logger
from dna_service.deps import build_deps, shutdown_deps
from dna_service.service import CONSUMER_GROUP, TOPIC_REPORT_READY, build_dna_consumer
from dna_service.settings import get_service_settings

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``report.ready`` until cancelled. Returns messages processed."""
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_dna_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "dna.worker.started",
        extra={"topic": TOPIC_REPORT_READY, "group": group_id},
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_REPORT_READY, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("dna.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
