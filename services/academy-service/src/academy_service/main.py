"""FastAPI entrypoint for the CIP academy service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on
   exit.
5. Mount routers.

In Step 1 the service exposes only the health + version surface; the
roster/session/dashboard/analytics/sharing routes mount from later steps.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from academy_service import __version__
from academy_service.deps import build_deps, shutdown_deps
from academy_service.health import router as health_router
from academy_service.health import version_router
from academy_service.settings import get_service_settings


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
        title="CIP academy-service",
        version=__version__,
        description=(
            "M18 Academy / Coach Platform. The institutional composition "
            "layer: rosters from M02 memberships, coach assignments, "
            "sessions and attendance, coach dashboards composing "
            "M04/M14/M16/M17 outputs within access rules, team analytics "
            "and fair leaderboards, and consented report sharing. Computes "
            "no cricket analysis of its own."
        ),
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)

    return app


app = create_app()
