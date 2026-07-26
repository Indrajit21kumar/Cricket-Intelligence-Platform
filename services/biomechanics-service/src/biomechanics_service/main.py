"""FastAPI entrypoint for the CIP reference service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on
   exit.
5. Mount routers.

New services scaffolded from this template inherit the same structure so
Book 3's cross-cutting requirements are satisfied by construction, per
M01 §1.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from biomechanics_service import __version__
from biomechanics_service.deps import build_deps, shutdown_deps
from biomechanics_service.health import router as health_router
from biomechanics_service.health import version_router
from biomechanics_service.routes import biomechanics_router, internal_router
from biomechanics_service.settings import get_service_settings


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
    """Factory — importable for tests, ASGI servers, and scaffolded services."""
    settings = get_service_settings()

    app = FastAPI(
        title="CIP biomechanics-service",
        version=__version__,
        description=(
            "M10 Biomechanics Engine. Consumes the perception fan-in "
            "(pose/bat/ball/shot + calibration + anthropometrics) and computes "
            "the 17 CIP-STD metrics (BM-01..BM-17) per stroke."
        ),
        lifespan=lifespan,
    )

    # Order matters: middleware wraps every route, exception handlers
    # produce the standard error envelope, observability instruments the app.
    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(biomechanics_router)
    app.include_router(internal_router)

    return app


app = create_app()
