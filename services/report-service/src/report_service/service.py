"""Report application service (M14 Step 8).

Where the pure pipeline meets I/O: fetch metrics/history/legend/video
artefacts, assemble the report (Step 2), attach video (Step 3) and the
grounded narrative (Step 5), persist, publish ``report.ready``, and audit.
Also carries one AI Coach turn: entitlement-gate (Step 7), answer or defer
(Step 6), persist, audit.

Trigger: report generation is driven by ``analysis.reasoned`` — the LAST
event in this report's dependency chain (M13, which itself waited on
M10/M11/M09). By the time it fires, biomechanics + physics are persisted and
fetchable by correlation_id, same fan-in pattern M13 used for its own facts.

Idempotent per correlation_id (mirrors M13's NFR-M13-03): a re-delivered
``analysis.reasoned`` updates one ``reports`` row rather than duplicating.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import audit_record
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from report_service.deps import Deps
from report_service.domain import reports_repo
from report_service.domain.coach import CoachGateResult, CoachLLMClient, ask_gated
from report_service.domain.entitlement import EntitlementClient
from report_service.domain.evidence import EvidenceChunk, build_evidence
from report_service.domain.narrative import LLMClient, build_narrative
from report_service.domain.report import (
    ReportStructure,
    attach_narrative,
    attach_video,
    build_report,
)
from report_service.domain.sources import (
    HistorySource,
    LegendSource,
    MetricsSource,
    VideoArtefactSource,
)
from report_service.domain.video import VideoAnnotator, build_markers

TOPIC_ANALYSIS_REASONED = "analysis.reasoned"
TOPIC_REPORT_READY = "report.ready"
TOPIC_REPORT_DLQ = "report.dlq"
CONSUMER_GROUP = "report-generator"


async def _attach_video_if_available(
    report: ReportStructure,
    *,
    correlation_id: str,
    video_source: VideoArtefactSource,
    video_annotator: VideoAnnotator,
) -> ReportStructure:
    artefacts = await video_source.load(correlation_id)
    if artefacts is None:
        # No clip/artefacts yet — the report ships without video, honestly
        # (annotated_video_ref stays None) rather than faking a render.
        return report
    markers = build_markers(report.findings, phases=artefacts.phases)
    video = await video_annotator.annotate(
        clip_ref=artefacts.clip_ref,
        pose_artefact_ref=artefacts.pose_artefact_ref,
        bat_artefact_ref=artefacts.bat_artefact_ref,
        markers=markers,
    )
    return attach_video(report, video)


async def generate_report(
    *,
    session_factory: async_sessionmaker[Any],
    metrics_source: MetricsSource,
    history_source: HistorySource,
    legend_source: LegendSource,
    video_source: VideoArtefactSource,
    video_annotator: VideoAnnotator,
    llm: LLMClient,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    reasoned: Mapping[str, Any],
) -> dict[str, Any]:
    """Assemble + narrate + annotate the report, persist, publish, audit."""
    metrics = await metrics_source.load(correlation_id)
    history = await history_source.load(str(person_id)) if person_id is not None else []
    legend_comparison = await legend_source.load(correlation_id)

    report = build_report(
        reasoned=reasoned,
        biomechanics=metrics.biomechanics,
        physics=metrics.physics,
        history=history,
        legend_comparison=legend_comparison,
    )
    report = await _attach_video_if_available(
        report,
        correlation_id=correlation_id,
        video_source=video_source,
        video_annotator=video_annotator,
    )

    evidence = build_evidence(findings=report.findings, legend_view=report.legend_view)
    narrative = await build_narrative(evidence, llm)
    report = attach_narrative(report, narrative)

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await reports_repo.upsert_report(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            kg_version=report.kg_version,
            structure=report.to_dict(),
            scores=report.scores.to_dict(),
            annotated_video_ref=report.annotated_video_ref,
            schema_version=report.schema_version,
            provisional=report.provisional,
        )
        await audit_record(
            session,
            action="report.generated",
            entity=f"report:{correlation_id}",
            actor="report-service",
            meta={"kg_version": report.kg_version, "provisional": report.provisional},
            tenant_id=tenant_id,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"report.ready:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "kg_version": report.kg_version,
            "schema_version": report.schema_version,
            "provisional": report.provisional,
            "annotated_video_ref": report.annotated_video_ref,
        },
    )
    await event_bus.publish(TOPIC_REPORT_READY, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_analysis_reasoned(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn an analysis.reasoned envelope into a report."""
    await generate_report(
        session_factory=deps.session_factory,
        metrics_source=deps.metrics_source,
        history_source=deps.history_source,
        legend_source=deps.legend_source,
        video_source=deps.video_source,
        video_annotator=deps.video_annotator,
        llm=deps.llm,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(envelope.payload.get("person_id")),
        reasoned=envelope.payload,
    )


def build_report_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over analysis.reasoned -> report.ready."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_analysis_reasoned(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_ANALYSIS_REASONED,
        dlq_topic=TOPIC_REPORT_DLQ,
        group_id=CONSUMER_GROUP,
    )


async def ask_coach(
    *,
    session_factory: async_sessionmaker[Any],
    entitlement: EntitlementClient,
    llm: CoachLLMClient,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID,
    coach_session_id: uuid.UUID | None,
    question: str,
    evidence: Sequence[EvidenceChunk],
) -> tuple[uuid.UUID, CoachGateResult]:
    """One AI Coach turn: gate, answer-or-defer, persist both sides, audit.

    Returns the (possibly newly-created) coach_session_id alongside the gate
    result, so the caller (route) can respond with the conversation to use
    for the next turn.
    """
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        if coach_session_id is None:
            created = await reports_repo.create_coach_session(
                session, tenant_id=tenant_id, person_id=person_id
            )
            coach_session_id = created["id"]

        await reports_repo.append_coach_message(
            session,
            tenant_id=tenant_id,
            coach_session_id=coach_session_id,
            role="user",
            content=question,
            citations=[],
            deferred=False,
        )

    result = await ask_gated(
        tenant_id=tenant_id,
        question=question,
        evidence=evidence,
        llm=llm,
        entitlement=entitlement,
        idempotency_key=f"ai_coach.consumed:{coach_session_id}:{question}",
    )

    if result.answer is not None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await reports_repo.append_coach_message(
                session,
                tenant_id=tenant_id,
                coach_session_id=coach_session_id,
                role="coach",
                content=result.answer.text,
                citations=list(result.answer.citations),
                deferred=result.answer.deferred,
            )
            await audit_record(
                session,
                action="coach.message_deferred"
                if result.answer.deferred
                else "coach.message_answered",
                entity=f"coach_session:{coach_session_id}",
                actor="report-service",
                meta={"citations": list(result.answer.citations)},
                tenant_id=tenant_id,
            )

    return coach_session_id, result
