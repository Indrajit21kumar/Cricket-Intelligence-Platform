"""Biomechanics application service (M10 Step 7).

Where the pure compute meets I/O: fetch the fan-in, compute the report, persist
it, publish ``biomechanics.metrics``.

Trigger: M10 is driven by ``shot.classified`` — the LAST perception event in
the chain, so by the time it fires, pose/bat/ball all exist and M09 has supplied
the shot type + phases the report is organised around. The handler fetches the
assembled fan-in by correlation_id and computes.

The published report is the SOLE biomechanical input to M11 (FR-M10-10,
AC-M10-07): it carries every metric M11 needs, so M11 never re-derives
kinematics from pose. Idempotent per correlation_id (NFR-M10-04).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from biomechanics_service.deps import Deps
from biomechanics_service.domain.report import compute_report
from biomechanics_service.domain.reports_repo import upsert_report
from biomechanics_service.domain.sources import StrokeSource
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer

TOPIC_SHOT_CLASSIFIED = "shot.classified"
TOPIC_BIOMECHANICS_METRICS = "biomechanics.metrics"
TOPIC_BIOMECHANICS_DLQ = "biomechanics.dlq"
CONSUMER_GROUP = "biomechanics-engine"


async def process_stroke(
    *,
    session_factory: async_sessionmaker[Any],
    stroke_source: StrokeSource,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    """Compute + persist + publish a BiomechanicsReport. None when uncomputable."""
    raw = await stroke_source.load(correlation_id)
    if raw is None:
        # No assembleable fan-in — nothing to measure.
        return None

    report = compute_report(raw)
    metrics_payload = report.metrics_payload()
    quality_payload = report.quality_payload()

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_report(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            shot_type=report.shot_type,
            shot_confidence=report.shot_confidence,
            phase_boundaries=report.phase_boundaries,
            phase_method=report.phase_method,
            metrics=metrics_payload,
            quality=quality_payload,
            schema_version=report.schema_version,
            out_of_expected_range=report.out_of_expected_range,
            provisional=report.provisional,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"biomechanics.metrics:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "shot_type": report.shot_type,
            "shot_confidence": report.shot_confidence,
            "phase_boundaries": report.phase_boundaries,
            "phase_method": report.phase_method,
            # The full metric set — M11 reads these and never touches pose.
            "metrics": metrics_payload,
            "quality": quality_payload,
            "out_of_expected_range": report.out_of_expected_range,
            "provisional": report.provisional,
            "schema_version": report.schema_version,
        },
    )
    await event_bus.publish(TOPIC_BIOMECHANICS_METRICS, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_shot_classified(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a shot.classified envelope into a report."""
    await process_stroke(
        session_factory=deps.session_factory,
        stroke_source=deps.stroke_source,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(envelope.payload.get("person_id")),
    )


def build_biomechanics_consumer(
    deps: Deps, *, idempotency_store: IdempotencyStore
) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over shot.classified -> biomechanics reports."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_shot_classified(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_SHOT_CLASSIFIED,
        dlq_topic=TOPIC_BIOMECHANICS_DLQ,
        group_id=CONSUMER_GROUP,
    )
