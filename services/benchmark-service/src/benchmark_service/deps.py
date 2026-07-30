"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
FastAPI's lifespan wires those calls; route handlers pull dependencies via
:func:`get_deps`. Every cross-service source (facts, player context, personal
baseline) is a Fake for now — no service in this build has a real HTTP
client wired for any of these adapters yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from benchmark_service.domain.personal_baseline import (
    FakePersonalBaselineSource,
    PersonalBaselineSource,
)
from benchmark_service.domain.sources import (
    FactsSource,
    FakeFactsSource,
    FakePlayerContextSource,
    PlayerContextSource,
)
from benchmark_service.settings import ServiceSettings
from cip_data import build_engine, build_session_factory
from cip_events import KafkaEventBus, RedisIdempotencyStore


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    facts_source: FactsSource
    player_context_source: PlayerContextSource
    personal_baseline_source: PersonalBaselineSource


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
        facts_source=FakeFactsSource(),
        player_context_source=FakePlayerContextSource(),
        personal_baseline_source=FakePersonalBaselineSource(),
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
