"""Reasoning application service (M13 Step 8).

Where the pure pipeline meets I/O: fetch the facts, ask M12 for applicable
rules, reason, persist, publish ``analysis.reasoned``.

Trigger: M13 is driven by ``physics.metrics`` — the LAST analytics event in the
chain, so by the time it fires, biomechanics + physics + shot are all present
and their facts assembleable. The handler fetches the fact set by
correlation_id, calls the knowledge source (M12) for the applicable rules, runs
the pipeline, persists, and publishes.

Idempotent per correlation_id (NFR-M13-03). Every finding traces to metrics +
rule version — no unsupported findings by construction (FR-M13-08).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from reasoning_service.deps import Deps
from reasoning_service.domain import reports_repo
from reasoning_service.domain.pipeline import ReasoningResult, reason
from reasoning_service.domain.sources import FactSource, KnowledgeSource

TOPIC_PHYSICS_METRICS = "physics.metrics"
TOPIC_ANALYSIS_REASONED = "analysis.reasoned"
TOPIC_REASONING_DLQ = "reasoning.dlq"
CONSUMER_GROUP = "reasoning-engine"


def _evidence_rows(result: ReasoningResult) -> list[dict[str, Any]]:
    """Rows for the finding_evidence table — reverse lookup for AC-M13-02."""
    return [
        {
            "finding_ref": finding.finding_id,
            "metric_ids": [e.metric_id for e in finding.evidence],
            "rule_id": finding.rule_id,
            "rule_version": finding.rule_version,
        }
        for finding in result.findings
    ]


async def process_stroke(
    *,
    session_factory: async_sessionmaker[Any],
    fact_source: FactSource,
    knowledge_source: KnowledgeSource,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    """Reason + persist + publish for one stroke. None when facts unavailable."""
    fact_set = await fact_source.load(correlation_id)
    if fact_set is None:
        # No assembleable facts — nothing to reason about.
        return None

    match_result = await knowledge_source.match(fact_set.match_payload())
    result = reason(
        fact_set,
        match_result.rules,
        conflicts=match_result.conflicts,
        kg_version=match_result.kg_version,
    )

    findings_payload = result.findings_payload()
    match_risk_payload = result.match_risk_payload()
    quality_payload = result.quality_payload()

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await reports_repo.upsert_result(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            shot_type=result.shot_type,
            shot_confidence=result.shot_confidence,
            kg_version=result.kg_version,
            findings=findings_payload,
            match_risk=match_risk_payload,
            quality=quality_payload,
            schema_version=result.schema_version,
            provisional=result.provisional,
        )
        await reports_repo.replace_evidence(
            session,
            tenant_id=tenant_id,
            result_id=row["id"],
            evidence_rows=_evidence_rows(result),
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"analysis.reasoned:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "shot_type": result.shot_type,
            "shot_confidence": result.shot_confidence,
            "kg_version": result.kg_version,
            "findings": findings_payload,
            "match_risk": match_risk_payload,
            "quality": quality_payload,
            "provisional": result.provisional,
            "schema_version": result.schema_version,
        },
    )
    await event_bus.publish(TOPIC_ANALYSIS_REASONED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_physics_metrics(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a physics.metrics envelope into a reasoning result."""
    await process_stroke(
        session_factory=deps.session_factory,
        fact_source=deps.fact_source,
        knowledge_source=deps.knowledge_source,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(envelope.payload.get("person_id")),
    )


def build_reasoning_consumer(
    deps: Deps, *, idempotency_store: IdempotencyStore
) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over physics.metrics -> analysis.reasoned."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_physics_metrics(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_PHYSICS_METRICS,
        dlq_topic=TOPIC_REASONING_DLQ,
        group_id=CONSUMER_GROUP,
    )
