"""FastAPI entrypoint for the CIP physics service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on exit.
5. Mount routers.

In Step 1 the service exposes only the health + version surface so the CI gate
sequence has a real service to test against; the compute + report routes are
mounted in Step 7.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from physics_service import __version__
from physics_service.deps import build_deps, shutdown_deps
from physics_service.health import router as health_router
from physics_service.health import version_router
from physics_service.routes import internal_router, physics_router
from physics_service.settings import get_service_settings


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
        title="CIP physics-service",
        version=__version__,
        description=(
            "M11 Physics Engine. Consumes the M10 BiomechanicsReport + M04 "
            "anthropometrics and computes the physics of the shot (PH-01..PH-11): "
            "MEASURED kinematics and ESTIMATED dynamics, each with provenance and "
            "confidence."
        ),
        lifespan=lifespan,
    )

    # Order matters: middleware wraps every route, exception handlers produce
    # the standard error envelope, observability instruments the app.
    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(physics_router)
    app.include_router(internal_router)

    return app


app = create_app()
