"""Pose worker — the process that consumes ``video.normalized`` (FR-M06-01).

M06 is queue-driven, not request-driven: the API in :mod:`pose_service.routes`
exists for reads and reprocessing, while the real work arrives as events. This
entrypoint runs the consume loop that drives them.

It is deliberately a SEPARATE process from the FastAPI app. Pose inference is
the GPU-bound stage, so the worker is what a GPU node pool runs and what
autoscaling targets — queue depth (consumer lag on ``video.normalized``) is
the scaling signal, and with no clips in flight the pool can scale to zero
without taking the read API down with it (§14, AC-M06-07). The k8s/KEDA
manifests that express that policy live with the platform infra; this module
is the workload they point at.

Run it with::

    python -m pose_service.worker
"""

from __future__ import annotations

import asyncio

from cip_observability import get_logger
from pose_service.deps import build_deps, shutdown_deps
from pose_service.service import CONSUMER_GROUP, TOPIC_VIDEO_NORMALIZED, build_pose_consumer
from pose_service.settings import get_service_settings

log = get_logger(__name__)


async def run_worker(*, group_id: str = CONSUMER_GROUP, stop_after: int | None = None) -> int:
    """Consume ``video.normalized`` until cancelled. Returns messages processed.

    ``stop_after`` bounds the loop and ``group_id`` isolates the offsets, so a
    test can run the real consumer against a real broker without inheriting
    the shared group's position; production leaves both at their defaults.
    """
    settings = get_service_settings()
    deps = await build_deps(settings)
    consumer = build_pose_consumer(deps, idempotency_store=deps.idempotency_store)
    processed = 0
    log.info("pose.worker.started", extra={"topic": TOPIC_VIDEO_NORMALIZED, "group": group_id})
    try:
        async for envelope in deps.event_bus.consume(TOPIC_VIDEO_NORMALIZED, group_id=group_id):
            await consumer.process_one(envelope)
            processed += 1
            if stop_after is not None and processed >= stop_after:
                break
    finally:
        log.info("pose.worker.stopped", extra={"processed": processed})
        await shutdown_deps(deps)
    return processed


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
