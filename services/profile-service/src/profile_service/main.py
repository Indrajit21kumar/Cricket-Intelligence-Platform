"""FastAPI entrypoint for the CIP profile-service (M04).

Wires cip-core middleware, cip-observability, lifespan-managed Deps, and
mounts the player-profile routers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from profile_service import __version__
from profile_service.deps import build_deps, shutdown_deps
from profile_service.health import router as health_router
from profile_service.health import version_router
from profile_service.routes import profiles_router
from profile_service.settings import get_service_settings


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
        title="CIP profile-service",
        version=__version__,
        description="Player Profile (M04) — attributes, Cricket DNA, history.",
        lifespan=lifespan,
    )

    # Order matters: middleware wraps every route, exception handlers
    # produce the standard error envelope, observability instruments the app.
    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(profiles_router)

    return app


app = create_app()
