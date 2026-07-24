"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
FastAPI's lifespan wires those calls; route handlers pull dependencies via
:func:`get_deps`.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from bat_service.domain.artefact import ArtefactStore, FakeArtefactStore
from bat_service.domain.clip import ClipLoader, FakeClipLoader
from bat_service.domain.detector import BatDetector, FakeBatDetector
from bat_service.domain.pose_client import FakePoseClient, PoseClient
from bat_service.settings import ServiceSettings
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
    #: Bat detector (fake by default; a trained GPU-served model later).
    detector: BatDetector
    #: Normalised-clip loader (fake by default; real decode-from-storage later).
    clip_loader: ClipLoader
    #: Bat-track artefact store (fake by default; real S3/MinIO later).
    artefact_store: ArtefactStore
    #: M06 pose reader for hand-bat association (fake by default).
    pose_client: PoseClient


async def build_deps(settings: ServiceSettings) -> Deps:
    """Construct + start every runtime singleton the service needs."""
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    event_bus = KafkaEventBus(bootstrap_servers=settings.kafka_bootstrap)
    await event_bus.start()
    idempotency_store = RedisIdempotencyStore(settings.redis_url)
    detector: BatDetector = FakeBatDetector()
    clip_loader: ClipLoader = FakeClipLoader()
    artefact_store: ArtefactStore = FakeArtefactStore()
    pose_client: PoseClient = FakePoseClient()
    return Deps(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        idempotency_store=idempotency_store,
        detector=detector,
        clip_loader=clip_loader,
        artefact_store=artefact_store,
        pose_client=pose_client,
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
