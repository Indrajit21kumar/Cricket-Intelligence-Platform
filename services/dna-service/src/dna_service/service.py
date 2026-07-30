"""DNA application service (M16 Step 7).

Where the pure pipeline meets I/O: check idempotency, gather evidence
(Step 2), update traits (Step 3) and recurring-fault/strength state
(Step 5), write through M04 (Step 1), persist the processing log, publish
``dna.updated``, audit.

Trigger: ``report.ready`` — M14's event, the point at which a stroke's
scores/findings/benchmark position are all fetchable by correlation_id
(the session_ref). M16 is person-anchored, not tenant-scoped (§9), so
unlike every tenant-scoped service in this build, events here use the NIL
UUID tenant sentinel + a real person_id in the payload — the same
convention M04 established for its own person-scoped events
(``profile.updated``/``dna.updated``).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import audit_record
from cip_data import admin_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from dna_service.deps import Deps
from dna_service.domain import dna_runs_repo
from dna_service.domain.decay import MODEL_VERSION as DECAY_MODEL_VERSION
from dna_service.domain.decay import update_trait
from dna_service.domain.dna_client import CurrentTrait, DNAReader, DNATraitWrite, DNAWriter
from dna_service.domain.evidence import gather_evidence
from dna_service.domain.inference import infer_strengths, infer_weak_areas
from dna_service.domain.sources import BenchmarkPositionSource, FindingsSource, ReportScoresSource

TOPIC_REPORT_READY = "report.ready"
TOPIC_DNA_UPDATED = "dna.updated"
TOPIC_DNA_DLQ = "dna.dlq"
CONSUMER_GROUP = "dna-engine"

#: NIL UUID sentinel for person-scoped events (M16 is person-anchored, no
#: tenant) — the same convention M04 established for profile.updated/dna.updated.
_NIL_TENANT = uuid.UUID(int=0)


def _as_float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


async def process_session(
    *,
    session_factory: async_sessionmaker[Any],
    report_scores_source: ReportScoresSource,
    findings_source: FindingsSource,
    benchmark_position_source: BenchmarkPositionSource,
    dna_reader: DNAReader,
    dna_writer: DNAWriter,
    event_bus: EventBus,
    person_id: uuid.UUID,
    session_ref: str,
) -> dict[str, Any] | None:
    """Compute + write + persist + publish for one session.

    Returns the processing-log row, or None when the session was already
    applied (NFR-M16-03) or there is nothing to evidence at all.
    """
    async with admin_session(session_factory) as session:
        existing = await dna_runs_repo.get_run(
            session, player_id=person_id, session_ref=session_ref
        )
    if existing is not None:
        return None

    report_scores = await report_scores_source.load(session_ref)
    findings = await findings_source.load(session_ref)
    benchmark_position = await benchmark_position_source.load(session_ref)

    evidence = gather_evidence(report_scores=report_scores or {}, source_ref=session_ref)
    current_traits = await dna_reader.read_traits(str(person_id))

    traits_updated: dict[str, Any] = {}
    writes: list[DNATraitWrite] = []

    for item in evidence:
        prior: CurrentTrait | None = current_traits.get(item.trait_key)
        prior_value = _as_float(prior.value) if prior is not None else None
        prior_confidence = prior.confidence if prior is not None else None
        update = update_trait(
            trait_key=item.trait_key,
            prior_value=prior_value,
            prior_confidence=prior_confidence,
            evidence_value=item.value,
            evidence_confidence=item.confidence,
        )
        traits_updated[item.trait_key] = update.to_dict()
        writes.append(
            DNATraitWrite(
                trait_key=item.trait_key,
                value=f"{update.new_value:.4f}",
                provenance=item.provenance,
                confidence=update.new_confidence,
                source_ref=session_ref,
            )
        )

    weak_areas_prior = current_traits.get("weak.areas")
    weak_areas_result = infer_weak_areas(
        prior_value=weak_areas_prior.value if weak_areas_prior is not None else None,
        findings=findings,
    )
    traits_updated[weak_areas_result.trait_key] = weak_areas_result.to_dict()
    writes.append(
        DNATraitWrite(
            trait_key=weak_areas_result.trait_key,
            value=weak_areas_result.stored_value,
            provenance="modelled",
            confidence=None,
            source_ref=session_ref,
        )
    )

    strengths_prior = current_traits.get("trait.strengths")
    strengths_result = infer_strengths(
        prior_value=strengths_prior.value if strengths_prior is not None else None,
        benchmark_position=benchmark_position,
    )
    traits_updated[strengths_result.trait_key] = strengths_result.to_dict()
    writes.append(
        DNATraitWrite(
            trait_key=strengths_result.trait_key,
            value=strengths_result.stored_value,
            provenance="modelled",
            confidence=None,
            source_ref=session_ref,
        )
    )

    await dna_writer.write_traits(person_id=str(person_id), updates=writes)

    async with admin_session(session_factory) as session:
        row = await dna_runs_repo.record_run(
            session,
            player_id=person_id,
            session_ref=session_ref,
            traits_updated=traits_updated,
            model_version=DECAY_MODEL_VERSION,
        )
        await audit_record(
            session,
            action="dna.updated",
            entity=f"person:{person_id}",
            actor="dna-service",
            meta={"session_ref": session_ref, "traits": list(traits_updated.keys())},
            tenant_id=None,
        )

    envelope = EventEnvelope(
        correlation_id=session_ref,
        tenant_id=_NIL_TENANT,
        schema_version="1.0.0",
        idempotency_key=f"dna.updated:{person_id}:{session_ref}",
        payload={
            "person_id": str(person_id),
            "session_ref": session_ref,
            "traits_updated": traits_updated,
            "model_version": DECAY_MODEL_VERSION,
        },
    )
    await event_bus.publish(TOPIC_DNA_UPDATED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_report_ready(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a report.ready envelope into a DNA update."""
    person_id = _parse_person(envelope.payload.get("person_id"))
    if person_id is None:
        # No player to attribute this update to — nothing to do.
        return
    await process_session(
        session_factory=deps.session_factory,
        report_scores_source=deps.report_scores_source,
        findings_source=deps.findings_source,
        benchmark_position_source=deps.benchmark_position_source,
        dna_reader=deps.dna_reader,
        dna_writer=deps.dna_writer,
        event_bus=deps.event_bus,
        person_id=person_id,
        session_ref=envelope.correlation_id,
    )


def build_dna_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over report.ready -> dna.updated."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_report_ready(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_REPORT_READY,
        dlq_topic=TOPIC_DNA_DLQ,
        group_id=CONSUMER_GROUP,
    )
