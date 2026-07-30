"""Report worker — the process that consumes ``analysis.reasoned`` (§10).

Separate process from the FastAPI app: report generation calls the LLM and
renders video, so this is the workload a worker pool runs independently of
request/response traffic.

Run it with::

    python -m report_service.worker
"""

from __future__ import annotations

import asyncio

from cip_observability import get_logger
from report_service.deps import build_deps, shutdown_deps
from report_service.service import CONSUMER_GROUP, TOPIC_ANALYSIS_REASONED, build_report_consumer
from report_service.settings import get_service_settings

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``analysis.reasoned`` until cancelled. Returns messages processed."""
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_report_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info(
        "report.worker.started",
        extra={"topic": TOPIC_ANALYSIS_REASONED, "group": group_id},
    )
    try:
        async for envelope in deps.event_bus.consume(TOPIC_ANALYSIS_REASONED, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("report.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
