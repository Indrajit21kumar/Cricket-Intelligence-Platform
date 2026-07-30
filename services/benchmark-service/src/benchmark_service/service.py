"""Benchmark application service (M15 Step 7).

Where the pure pipeline meets I/O: fetch facts + player context + released
profiles + personal baseline, compute the comparison (Steps 2-6), persist,
publish ``benchmark.compared``.

Trigger: ``physics.metrics`` — the LAST analytics event in this comparison's
dependency chain (M10 biomechanics -> M11 physics), the same convention M13
established for its own trigger; by the time it fires, biomechanics is
already persisted and fetchable by correlation_id.

Idempotent per correlation_id (NFR-M15-03): a re-delivered ``physics.metrics``
updates one ``comparisons`` row rather than duplicating.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from benchmark_service.deps import Deps
from benchmark_service.domain import comparisons_repo, profiles_repo
from benchmark_service.domain.personal_baseline import PersonalBaselineSource
from benchmark_service.domain.pipeline import compute_comparison
from benchmark_service.domain.sources import FactsSource, PlayerContextSource
from cip_data import admin_session, tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer

TOPIC_PHYSICS_METRICS = "physics.metrics"
TOPIC_BENCHMARK_COMPARED = "benchmark.compared"
TOPIC_BENCHMARK_DLQ = "benchmark.dlq"
CONSUMER_GROUP = "benchmark-comparator"


async def compare_stroke(
    *,
    session_factory: async_sessionmaker[Any],
    facts_source: FactsSource,
    player_context_source: PlayerContextSource,
    personal_baseline_source: PersonalBaselineSource,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
) -> dict[str, Any] | None:
    """Compare + persist + publish for one stroke. None when nothing is comparable."""
    facts = await facts_source.load(correlation_id)
    context = await player_context_source.load(correlation_id)
    if not facts or context is None:
        # No assembleable facts or no shot context yet — nothing to compare.
        return None

    async with admin_session(session_factory) as session:
        all_profiles = await profiles_repo.list_released_profiles(session)

    personal_baselines = (
        await personal_baseline_source.load(str(person_id)) if person_id is not None else []
    )

    result = compute_comparison(
        correlation_id=correlation_id,
        person_id=str(person_id) if person_id else None,
        facts=facts,
        all_profiles=all_profiles,
        shot_type=context.shot_type,
        skill_tier=context.skill_tier,
        age_band=context.age_band,
        personal_baselines=personal_baselines,
    )

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await comparisons_repo.upsert_comparison(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            per_metric=result.per_metric,
            legend_similarity=result.legend_similarity,
            benchmark_version=result.benchmark_version,
            confidence=result.confidence,
            schema_version=result.schema_version,
            provisional=result.provisional,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"benchmark.compared:{correlation_id}",
        payload=result.to_dict(),
    )
    await event_bus.publish(TOPIC_BENCHMARK_COMPARED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_physics_metrics(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a physics.metrics envelope into a comparison."""
    await compare_stroke(
        session_factory=deps.session_factory,
        facts_source=deps.facts_source,
        player_context_source=deps.player_context_source,
        personal_baseline_source=deps.personal_baseline_source,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(envelope.payload.get("person_id")),
    )


def build_benchmark_consumer(
    deps: Deps, *, idempotency_store: IdempotencyStore
) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over physics.metrics -> benchmark.compared."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_physics_metrics(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_PHYSICS_METRICS,
        dlq_topic=TOPIC_BENCHMARK_DLQ,
        group_id=CONSUMER_GROUP,
    )
