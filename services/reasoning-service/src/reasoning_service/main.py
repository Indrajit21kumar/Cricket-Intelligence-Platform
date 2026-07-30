"""FastAPI entrypoint for the CIP reasoning service.

1. Build service :class:`ServiceSettings`.
2. Install ``cip-core`` middleware + exception handlers.
3. Install ``cip-observability``.
4. In the lifespan, build/stash the runtime :class:`Deps`.
5. Mount routers.

In Step 1 the service exposes only the health + version surface; the run + read
routes are mounted in Step 8.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from reasoning_service import __version__
from reasoning_service.deps import build_deps, shutdown_deps
from reasoning_service.health import router as health_router
from reasoning_service.health import version_router
from reasoning_service.routes import internal_router, reasoning_router
from reasoning_service.settings import get_service_settings


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
        title="CIP reasoning-service",
        version=__version__,
        description=(
            "M13 Reasoning Engine. Executes M12 rules over the M10/M11/M09 facts "
            "of a stroke into explained, evidence-linked findings "
            "(what / why / impact / drill), and publishes analysis.reasoned."
        ),
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(reasoning_router)
    app.include_router(internal_router)

    return app


app = create_app()
