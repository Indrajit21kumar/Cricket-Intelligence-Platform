"""The real event path: a platform topic -> warehouse worker -> fact row (M20 Step 1).

Unlike the repo tests (which call :func:`ingest_envelope` directly), this
drives :func:`run_worker` against a real broker, so the wiring between a
producing service's event and the warehouse is proven end to end rather than
assumed.

Uses ``report.shared`` (a low-traffic M18 topic with no accumulated backlog
at the time this test was written) rather than a high-traffic topic like
``video.normalized`` — the same long-lived-dev-broker replay cost that
pose-service's own worker test documents (the group reads from earliest)
applies here too; picking a topic with nothing to replay keeps this test
fast regardless.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import uuid

import pytest
from admin_service.worker import run_worker
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_events import EventEnvelope, KafkaEventBus

pytestmark = pytest.mark.integration

DEFAULT_BOOTSTRAP = "localhost:9092"
TEST_TOPIC = "report.shared"


async def _read_fact_row(session_factory: async_sessionmaker, dedupe_key: str) -> dict | None:
    async with session_factory() as session:
        row = (
            (
                await session.execute(
                    text(
                        "SELECT event_topic, tenant_id, correlation_id "
                        "FROM warehouse.fact_usage_event WHERE dedupe_key = :k"
                    ),
                    {"k": dedupe_key},
                )
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


async def test_worker_ingests_a_real_published_event(
    session_factory: async_sessionmaker,
) -> None:
    correlation_id = f"m20-wrk-{uuid.uuid4().hex[:10]}"
    tenant_id = uuid.uuid4()
    dedupe_key = f"{TEST_TOPIC}:{correlation_id}"

    group = f"admin-warehouse-test-{uuid.uuid4().hex[:8]}"
    worker = asyncio.create_task(run_worker(group_id=group, topics=(TEST_TOPIC,)))
    await asyncio.sleep(2.0)  # let the group join before publishing

    bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
    await bus.start()
    row: dict | None = None
    try:
        await bus.publish(
            TEST_TOPIC,
            EventEnvelope(
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                schema_version="1.0.0",
                idempotency_key=dedupe_key,
                payload={"report_id": str(uuid.uuid4())},
            ),
        )
        for _ in range(60):
            await asyncio.sleep(0.5)
            row = await _read_fact_row(session_factory, dedupe_key)
            if row is not None:
                break
    finally:
        worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker
        await bus.stop()

    assert row is not None, "worker did not ingest the published event"
    assert row["event_topic"] == TEST_TOPIC
    assert row["tenant_id"] == tenant_id
    assert row["correlation_id"] == correlation_id
