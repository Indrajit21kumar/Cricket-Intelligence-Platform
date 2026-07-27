"""Physics application service (M11 Step 7).

Where the pure compute meets I/O: fetch the inputs, compute the report, persist
it, publish ``physics.metrics``.

Trigger: M11 is driven by ``biomechanics.metrics`` — the M10 report. When it
fires, the handler fetches the assembled inputs (the M10 report + M04
anthropometrics) by correlation_id and computes. The event is the trigger; the
source of truth is the persisted report, so a reprocess produces the same
physics.

The published PhysicsReport carries every PH quantity with its provenance +
confidence, so downstream (M12/M13 reasoning, M14 report, M15 benchmark) never
has to re-derive physics. Idempotent per correlation_id (NFR-M11-03).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from physics_service.deps import Deps
from physics_service.domain.report import compute_report
from physics_service.domain.reports_repo import upsert_report
from physics_service.domain.sources import BiomechanicsSource

TOPIC_BIOMECHANICS_METRICS = "biomechanics.metrics"
TOPIC_PHYSICS_METRICS = "physics.metrics"
TOPIC_PHYSICS_DLQ = "physics.dlq"
CONSUMER_GROUP = "physics-engine"


async def process_stroke(
    *,
    session_factory: async_sessionmaker[Any],
    source: BiomechanicsSource,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    """Compute + persist + publish a PhysicsReport. None when uncomputable."""
    inputs = await source.load(correlation_id)
    if inputs is None:
        # No assembleable biomechanics — there is nothing to turn into physics.
        return None

    report = compute_report(inputs.bio, inputs.anthropometrics)
    quantities_payload = report.quantities_payload()
    kinetic_chain_payload = report.kinetic_chain_payload()
    quality_payload = report.quality_payload()

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_report(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            shot_type=report.shot_type,
            shot_confidence=report.shot_confidence,
            quantities=quantities_payload,
            kinetic_chain=kinetic_chain_payload,
            quality=quality_payload,
            schema_version=report.schema_version,
            model_version=report.model_version,
            out_of_expected_range=report.out_of_expected_range,
            provisional=report.provisional,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"physics.metrics:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "shot_type": report.shot_type,
            "shot_confidence": report.shot_confidence,
            # The full quantity set — provenance + confidence per PH — plus the
            # kinetic chain. Downstream reads these and never re-derives physics.
            "quantities": quantities_payload,
            "kinetic_chain": kinetic_chain_payload,
            "quality": quality_payload,
            "out_of_expected_range": report.out_of_expected_range,
            "provisional": report.provisional,
            "model_version": report.model_version,
            "schema_version": report.schema_version,
        },
    )
    await event_bus.publish(TOPIC_PHYSICS_METRICS, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_biomechanics_metrics(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a biomechanics.metrics envelope into a report."""
    await process_stroke(
        session_factory=deps.session_factory,
        source=deps.source,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(envelope.payload.get("person_id")),
    )


def build_physics_consumer(
    deps: Deps, *, idempotency_store: IdempotencyStore
) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over biomechanics.metrics -> physics reports."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_biomechanics_metrics(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_BIOMECHANICS_METRICS,
        dlq_topic=TOPIC_PHYSICS_DLQ,
        group_id=CONSUMER_GROUP,
    )
