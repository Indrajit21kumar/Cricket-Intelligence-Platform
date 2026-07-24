"""The real event path: video.normalized -> worker -> pose run (AC-M06-01/05).

Unlike the compute tests (which call the consumer's state machine directly),
this drives :func:`run_worker` — the actual process a GPU pool runs — against
a real broker, so the wiring between M05's event and M06's pipeline is proven
end to end rather than assumed.

Slow on a long-lived dev broker: the group reads from earliest, so the worker
replays every ``video.normalized`` left by previous runs before reaching this
test's clip. CI starts Redpanda fresh, where there is nothing to replay.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid

import pytest
from sqlalchemy import text

from cip_data.engine import build_engine, build_session_factory, tenant_session
from cip_events import EventEnvelope, KafkaEventBus
from pose_service.service import TOPIC_VIDEO_NORMALIZED
from pose_service.worker import run_worker

pytestmark = pytest.mark.integration

DEFAULT_BOOTSTRAP = "localhost:9092"


async def _read_run(database_url: str, tenant_id: uuid.UUID, correlation_id: str) -> dict | None:
    engine = build_engine(database_url)
    try:
        session_factory = build_session_factory(engine)
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            row = (
                (
                    await session.execute(
                        text(
                            "SELECT person_id, subject_status, quality, artefact_ref, "
                            "depth_estimated FROM pose_runs WHERE correlation_id = :c"
                        ),
                        {"c": correlation_id},
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row else None
    finally:
        await engine.dispose()


async def test_worker_consumes_video_normalized(
    _migrated_database: str, tenant_id: uuid.UUID
) -> None:
    correlation_id = f"m06-wrk-{uuid.uuid4().hex[:10]}"
    person_id = uuid.uuid4()

    # Own consumer group: the shared one carries committed offsets from other
    # runs, and the topic replays from earliest, so this keeps the test's view
    # of the stream its own.
    group = f"pose-engine-test-{uuid.uuid4().hex[:8]}"
    worker = asyncio.create_task(run_worker(group_id=group))
    await asyncio.sleep(2.0)  # let the group join before publishing

    bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
    await bus.start()
    row: dict | None = None
    try:
        await bus.publish(
            TOPIC_VIDEO_NORMALIZED,
            EventEnvelope(
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                schema_version="1.0.0",
                idempotency_key=f"{TOPIC_VIDEO_NORMALIZED}:{correlation_id}",
                payload={
                    "ingestion_id": str(uuid.uuid4()),
                    "person_id": str(person_id),
                    "normalized_ref": f"tenant/{tenant_id}/normalized/{correlation_id}.mp4",
                    "camera_angle": "side_on",
                    "spatial_confidence": "high",
                    "depth_estimated": True,
                    "quality_flags": [],
                },
            ),
        )
        # The worker replays whatever backlog the topic holds before reaching
        # ours, so wait for our own clip rather than for a message count.
        for _ in range(240):
            await asyncio.sleep(0.5)
            row = await _read_run(_migrated_database, tenant_id, correlation_id)
            if row is not None:
                break
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await bus.stop()

    assert row is not None, "worker did not persist a pose run"
    assert row["person_id"] == person_id
    assert row["subject_status"] == "tracked"
    assert row["quality"] == "ok"
    assert row["artefact_ref"] is not None
    # AC-M06-03: the depth flag from the capture survives the whole path.
    assert row["depth_estimated"] is True
