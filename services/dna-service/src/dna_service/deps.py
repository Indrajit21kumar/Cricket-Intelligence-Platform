"""Shared runtime dependencies — one per process, held on ``app.state``.

Everything that needs an open connection (DB engine, Kafka bus, Redis client)
is built in :func:`build_deps` at startup and shut down in :func:`shutdown_deps`.
FastAPI's lifespan wires those calls; route handlers pull dependencies via
:func:`get_deps`. Every cross-service source (M14 scores, M13 findings, M15
benchmark position, M04 DNA read/write) is a Fake for now — no service in
this build has a real HTTP client wired for any of these adapters yet.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from cip_data import build_engine, build_session_factory
from cip_events import KafkaEventBus, RedisIdempotencyStore
from dna_service.domain.dna_client import (
    DNAReader,
    DNAWriter,
    FakeDNAReader,
    FakeDNAWriter,
)
from dna_service.domain.sources import (
    BenchmarkPositionSource,
    FakeBenchmarkPositionSource,
    FakeFindingsSource,
    FakeReportScoresSource,
    FindingsSource,
    ReportScoresSource,
)
from dna_service.settings import ServiceSettings


@dataclass(slots=True)
class Deps:
    """Runtime singletons for the service."""

    settings: ServiceSettings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    event_bus: KafkaEventBus
    idempotency_store: RedisIdempotencyStore
    report_scores_source: ReportScoresSource
    findings_source: FindingsSource
    benchmark_position_source: BenchmarkPositionSource
    dna_reader: DNAReader
    dna_writer: DNAWriter


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
        report_scores_source=FakeReportScoresSource(),
        findings_source=FakeFindingsSource(),
        benchmark_position_source=FakeBenchmarkPositionSource(),
        dna_reader=FakeDNAReader(),
        dna_writer=FakeDNAWriter(),
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
