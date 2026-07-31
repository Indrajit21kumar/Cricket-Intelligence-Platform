"""FastAPI entrypoint for the CIP admin service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus)
   and stash them on ``app.state``. Shut them down on exit.
5. Mount routers.

Step 1 mounts only health/version; the admin console routes are added from
Step 2 onward, restricted to ``platform_admin``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from admin_service import __version__
from admin_service.deps import build_deps, shutdown_deps
from admin_service.health import router as health_router
from admin_service.health import version_router
from admin_service.routes import admin_router
from admin_service.settings import get_service_settings


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
        title="CIP admin-service",
        version=__version__,
        description=(
            "M20 Admin & Platform Analytics. The operator's console and "
            "the platform's analytics warehouse: user/tenant administration, "
            "content moderation, revenue/usage reporting, per-model "
            "oversight, and the biomechanics review queue. Restricted to "
            "platform_admin; every privileged action is audited."
        ),
        lifespan=lifespan,
    )

    # Order matters: middleware wraps every route, exception handlers
    # produce the standard error envelope, observability instruments the app.
    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(admin_router)

    return app


app = create_app()
