"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
Every cross-service source is a Fake for now (Step 8) — no service in this
build has a real HTTP client wired for any of these adapters yet; swapping
one in later only touches this function.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cip_data import build_engine, build_session_factory
from cip_events import KafkaEventBus, RedisIdempotencyStore
from report_service.domain.coach import CoachLLMClient, FakeCoachLLMClient
from report_service.domain.entitlement import EntitlementClient, FakeEntitlementClient
from report_service.domain.narrative import FakeLLMClient, LLMClient
from report_service.domain.sources import (
    FakeHistorySource,
    FakeLegendSource,
    FakeMetricsSource,
    FakeVideoArtefactSource,
    HistorySource,
    LegendSource,
    MetricsSource,
    VideoArtefactSource,
)
from report_service.domain.video import FakeVideoAnnotator, VideoAnnotator
from report_service.settings import ServiceSettings


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    metrics_source: MetricsSource
    history_source: HistorySource
    legend_source: LegendSource
    video_source: VideoArtefactSource
    video_annotator: VideoAnnotator
    llm: LLMClient
    coach_llm: CoachLLMClient
    entitlement: EntitlementClient


async def build_deps(settings: ServiceSettings) -> Deps:
    """Construct + start every runtime singleton the service needs."""
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    event_bus = KafkaEventBus(bootstrap_servers=settings.kafka_bootstrap)
    await event_bus.start()
    idempotency_store = RedisIdempotencyStore(settings.redis_url)
    return Deps(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        idempotency_store=idempotency_store,
        metrics_source=FakeMetricsSource(),
        history_source=FakeHistorySource(),
        legend_source=FakeLegendSource(),
        video_source=FakeVideoArtefactSource(),
        video_annotator=FakeVideoAnnotator(),
        llm=FakeLLMClient(),
        coach_llm=FakeCoachLLMClient(),
        entitlement=FakeEntitlementClient(),
    )


async def shutdown_deps(deps: Deps) -> None:
    """Reverse of :func:`build_deps` — close every open connection."""
    await deps.event_bus.stop()
    await deps.idempotency_store.close()
    await deps.engine.dispose()


def get_deps(request: Request) -> Deps:
    """FastAPI dependency — pulls the process-wide Deps off app.state."""
    deps: Deps = request.app.state.deps
    return deps
