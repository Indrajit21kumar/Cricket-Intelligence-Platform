"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
FastAPI's lifespan wires those calls; route handlers pull dependencies via
:func:`get_deps`.
"""

from __future__ import annotations

from dataclasses import dataclass

import redis.asyncio as aioredis
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cip_data import build_engine, build_session_factory
from cip_events import KafkaEventBus, RedisIdempotencyStore
from identity_service.domain.oauth import (
    OAuthProvider,
    google_provider,
    microsoft_provider,
)
from identity_service.settings import ServiceSettings


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    #: Raw Redis client for the brute-force lockout counters (Step 8).
    redis: aioredis.Redis
    #: Configured OAuth providers by name (Step 7). Empty if no credentials.
    oauth_providers: dict[str, OAuthProvider]


def _build_oauth_providers(settings: ServiceSettings) -> dict[str, OAuthProvider]:
    """Register only the providers whose credentials are configured."""
    providers: dict[str, OAuthProvider] = {}
    if settings.google_client_id and settings.google_client_secret:
        providers["google"] = google_provider(
            settings.google_client_id, settings.google_client_secret
        )
    if settings.microsoft_client_id and settings.microsoft_client_secret:
        providers["microsoft"] = microsoft_provider(
            settings.microsoft_client_id, settings.microsoft_client_secret
        )
    return providers


async def build_deps(settings: ServiceSettings) -> Deps:
    """Construct + start every runtime singleton the service needs."""
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    event_bus = KafkaEventBus(bootstrap_servers=settings.kafka_bootstrap)
    await event_bus.start()
    idempotency_store = RedisIdempotencyStore(settings.redis_url)
    redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return Deps(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        idempotency_store=idempotency_store,
        redis=redis,
        oauth_providers=_build_oauth_providers(settings),
    )


async def shutdown_deps(deps: Deps) -> None:
    """Reverse of :func:`build_deps` — close every open connection."""
    await deps.event_bus.stop()
    await deps.idempotency_store.close()
    await deps.redis.aclose()
    await deps.engine.dispose()


def get_deps(request: Request) -> Deps:
    """FastAPI dependency — pulls the process-wide Deps off app.state."""
    deps: Deps = request.app.state.deps
    return deps
