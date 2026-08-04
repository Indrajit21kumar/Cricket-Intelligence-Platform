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
from pose_service.domain.artefact import ArtefactStore, FakeArtefactStore
from pose_service.domain.clip import ClipLoader, FakeClipLoader, RealClipLoader
from pose_service.domain.model import FakePoseModel, PoseModel, RealPoseModel
from pose_service.settings import ServiceSettings


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    #: Pose-estimation model (fake by default; real GPU-served model later).
    model: PoseModel
    #: Normalised-clip loader (fake by default; real decode-from-storage later).
    clip_loader: ClipLoader
    #: Keypoint-artefact store (fake by default; real S3/MinIO later).
    artefact_store: ArtefactStore


async def build_deps(settings: ServiceSettings) -> Deps:
    """Construct + start every runtime singleton the service needs."""
    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    event_bus = KafkaEventBus(bootstrap_servers=settings.kafka_bootstrap)
    await event_bus.start()
    idempotency_store = RedisIdempotencyStore(settings.redis_url)
    model: PoseModel
    clip_loader: ClipLoader
    if settings.use_real_pose_model:
        # Loader + model move together: a real model has no pixels to run on
        # unless the loader actually decoded the clip.
        model = RealPoseModel(weights=settings.pose_model_weights)
        clip_loader = RealClipLoader(root=Path(settings.local_storage_root))
    else:
        model = FakePoseModel()
        clip_loader = FakeClipLoader()
    artefact_store: ArtefactStore = FakeArtefactStore()
    return Deps(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        event_bus=event_bus,
        idempotency_store=idempotency_store,
        model=model,
        clip_loader=clip_loader,
        artefact_store=artefact_store,
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
