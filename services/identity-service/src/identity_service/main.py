"""FastAPI entrypoint for the CIP identity-service (M02).

Same shape as the reference-service template — wires cip-core middleware,
cip-observability (logs + traces + metrics), and mounts the auth routes
that replace the scaffolded demo endpoint.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from identity_service import __version__
from identity_service.deps import build_deps, shutdown_deps
from identity_service.health import router as health_router
from identity_service.health import version_router
from identity_service.memberships_routes import me_router, membership_router
from identity_service.routes import router as auth_router
from identity_service.settings import get_service_settings


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
        title="CIP identity-service",
        version=__version__,
        description="Identity & Authentication (M02).",
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(auth_router)
    app.include_router(membership_router)
    app.include_router(me_router)

    return app


app = create_app()
