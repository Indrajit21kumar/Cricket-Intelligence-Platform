"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
FastAPI's lifespan wires those calls; route handlers pull dependencies via
:func:`get_deps`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cip_data import build_engine, build_session_factory
from cip_events import KafkaEventBus, RedisIdempotencyStore
from video_service.domain.entitlement import EntitlementClient, FakeEntitlementClient
from video_service.domain.processor import FakeVideoProcessor, RealVideoProcessor, VideoProcessor
from video_service.domain.profile_client import FakeProfileClient, ProfileClient
from video_service.domain.storage import (
    FakeStorageProvider,
    LocalFilesystemStorageProvider,
    StorageProvider,
)
from video_service.settings import ServiceSettings


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    #: Object-storage adapter (fake by default; real S3/MinIO plugs in later).
    storage: StorageProvider
    #: M03 entitlement + usage client (fake by default; real HTTP later).
    entitlement_client: EntitlementClient
    #: Preprocessing adapter (fake by default; real ffmpeg/OpenCV later).
    video_processor: VideoProcessor
    #: M04 profile client for the height calibration fallback (fake by default).
    profile_client: ProfileClient


async def build_deps(settings: ServiceSettings) -> Deps:
    """Construct + start every runtime singleton the service needs."""
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    event_bus = KafkaEventBus(bootstrap_servers=settings.kafka_bootstrap)
    await event_bus.start()
    idempotency_store = RedisIdempotencyStore(settings.redis_url)
    storage: StorageProvider
    video_processor: VideoProcessor
    if settings.use_real_pipeline:
        # Storage + processor move together: a real processor has nothing to
        # decode unless real bytes actually landed on disk.
        root = Path(settings.local_storage_root)
        storage = LocalFilesystemStorageProvider(
            root=root, public_base_url=settings.public_base_url
        )
        video_processor = RealVideoProcessor(root=root)
    else:
        storage = FakeStorageProvider()
        video_processor = FakeVideoProcessor()
    entitlement_client: EntitlementClient = FakeEntitlementClient()
    profile_client: ProfileClient = FakeProfileClient()
    return Deps(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        idempotency_store=idempotency_store,
        storage=storage,
        entitlement_client=entitlement_client,
        video_processor=video_processor,
        profile_client=profile_client,
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
