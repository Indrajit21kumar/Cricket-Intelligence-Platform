"""FastAPI entrypoint for the CIP DNA service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on
   exit.
5. Mount routers.

The recompute route mounts alongside health + version.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from dna_service import __version__
from dna_service.deps import build_deps, shutdown_deps
from dna_service.health import router as health_router
from dna_service.health import version_router
from dna_service.routes import internal_router
from dna_service.settings import get_service_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_service_settings()
    deps = await build_deps(settings)
    app.state.deps = deps
    try:
        yield
    finally:
        await shutdown_deps(deps)


def create_app() -> FastAPI:
    """Factory — importable for tests + ASGI servers."""
    settings = get_service_settings()

    app = FastAPI(
        title="CIP dna-service",
        version=__version__,
        description=(
            "M16 Cricket DNA. The engine that computes a player's evolving "
            "technical trait profile (performance/tendency/learning/style) "
            "from each session's metrics, findings, and benchmark position, "
            "and writes versioned updates through M04's write path — the "
            "only writer of trait values. Publishes dna.updated."
        ),
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(internal_router)

    return app


app = create_app()
