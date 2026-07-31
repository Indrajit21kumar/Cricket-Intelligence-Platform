"""Learning application service (M17 Step 7).

Where the pure pipeline meets I/O: resolve tenant, check idempotency,
evaluate the prior plan against this cycle's evidence, compute the new
plan (Steps 2-6), persist, publish ``plan.updated``, audit.

Trigger: ``dna.updated`` — M16's event, person-scoped (NIL tenant
sentinel, mirroring M04's own events). Since ``training_plans`` is
tenant-scoped personal data (§9), :class:`~learning_service.domain.sources.TenantResolver`
bridges the two scoping regimes — a first for this build: a person-scoped
trigger feeding a tenant-scoped consumer.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import audit_record
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from learning_service.deps import Deps
from learning_service.domain import plans_repo
from learning_service.domain.evaluation import adaptation_multiplier, evaluate_plan
from learning_service.domain.pipeline import compute_plan
from learning_service.domain.sources import (
    BenchmarkComparisonSource,
    DNAHistorySource,
    FindingsSource,
    PersonalDeviationSource,
    TenantResolver,
)

TOPIC_DNA_UPDATED = "dna.updated"
TOPIC_PLAN_UPDATED = "plan.updated"
TOPIC_PLAN_DLQ = "plan.dlq"
CONSUMER_GROUP = "learning-planner"


async def build_plan(
    *,
    session_factory: async_sessionmaker[Any],
    findings_source: FindingsSource,
    benchmark_source: BenchmarkComparisonSource,
    dna_history_source: DNAHistorySource,
    deviation_source: PersonalDeviationSource,
    tenant_resolver: TenantResolver,
    event_bus: EventBus,
    person_id: uuid.UUID,
    session_ref: str,
) -> dict[str, Any] | None:
    """Build + persist + publish one player's plan for this cycle.

    None when the tenant can't be resolved, or the cycle was already
    processed (NFR-M17-03).
    """
    tenant_id = await tenant_resolver.resolve(str(person_id))
    if tenant_id is None:
        return None

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        existing = await plans_repo.get_plan_by_session(
            session, tenant_id=tenant_id, person_id=person_id, session_ref=session_ref
        )
    if existing is not None:
        return None

    findings = await findings_source.load(session_ref)
    comparisons = await benchmark_source.load(session_ref)
    trait_deltas = await dna_history_source.load(str(person_id))
    deviations = await deviation_source.load(str(person_id))

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        prior = await plans_repo.get_active_plan(session, tenant_id=tenant_id, person_id=person_id)

    adaptation_by_target_ref: dict[str, float] = {}
    if prior is not None:
        prior_items = prior.get("items") or []
        evaluations = evaluate_plan(prior_items, comparisons, evidence_ref=session_ref)
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            for evaluation in evaluations:
                await plans_repo.record_evaluation(
                    session,
                    tenant_id=tenant_id,
                    plan_id=prior["id"],
                    target_ref=evaluation.target_ref,
                    met=evaluation.met,
                    evidence_ref=evaluation.evidence_ref,
                )
        adaptation_by_target_ref = {
            evaluation.target_ref: adaptation_multiplier(
                evaluations, target_ref=evaluation.target_ref
            )
            for evaluation in evaluations
        }

    result = compute_plan(
        findings=findings,
        benchmark_comparisons_by_metric=comparisons,
        consistency_deviations=deviations,
        trait_deltas=trait_deltas,
        adaptation_by_target_ref=adaptation_by_target_ref,
    )

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await plans_repo.insert_plan(
            session,
            tenant_id=tenant_id,
            person_id=person_id,
            session_ref=session_ref,
            stage=result.stage,
            items=result.items,
            schema_version=result.schema_version,
        )
        if prior is not None:
            await plans_repo.deactivate_plan(session, tenant_id=tenant_id, plan_id=prior["id"])
        await audit_record(
            session,
            action="plan.updated",
            entity=f"person:{person_id}",
            actor="learning-service",
            meta={
                "session_ref": session_ref,
                "stage": result.stage,
                "item_count": len(result.items),
            },
            tenant_id=tenant_id,
        )

    envelope = EventEnvelope(
        correlation_id=session_ref,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"plan.updated:{person_id}:{session_ref}",
        payload={"person_id": str(person_id), "session_ref": session_ref, **result.to_dict()},
    )
    await event_bus.publish(TOPIC_PLAN_UPDATED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_dna_updated(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a dna.updated envelope into a training plan."""
    person_id = _parse_person(envelope.payload.get("person_id"))
    session_ref = envelope.payload.get("session_ref")
    if person_id is None or not isinstance(session_ref, str):
        return
    await build_plan(
        session_factory=deps.session_factory,
        findings_source=deps.findings_source,
        benchmark_source=deps.benchmark_source,
        dna_history_source=deps.dna_history_source,
        deviation_source=deps.deviation_source,
        tenant_resolver=deps.tenant_resolver,
        event_bus=deps.event_bus,
        person_id=person_id,
        session_ref=session_ref,
    )


def build_plan_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over dna.updated -> plan.updated."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_dna_updated(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_DNA_UPDATED,
        dlq_topic=TOPIC_PLAN_DLQ,
        group_id=CONSUMER_GROUP,
    )
