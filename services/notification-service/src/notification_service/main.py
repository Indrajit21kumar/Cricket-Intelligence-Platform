"""FastAPI entrypoint for the CIP notification service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on
   exit.
5. Mount routers.

Step 6 mounts the inbox/preferences/webhook routes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from notification_service import __version__
from notification_service.deps import build_deps, shutdown_deps
from notification_service.health import router as health_router
from notification_service.health import version_router
from notification_service.routes import notifications_router, preferences_router, webhooks_router
from notification_service.settings import get_service_settings


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
        title="CIP notification-service",
        version=__version__,
        description=(
            "M19 Notification. The platform's outbound messaging service: "
            "listens for events across the system (report ready, plan "
            "updated, billing/dunning, sessions, identity), maps them to "
            "notification types, and delivers via email/push/in-app — only "
            "to consented, contactable recipients, honouring preferences "
            "and quiet hours. Decides how/whether to deliver; producers "
            "decide what happened."
        ),
        lifespan=lifespan,
    )

    # Order matters: middleware wraps every route, exception handlers
    # produce the standard error envelope, observability instruments the app.
    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(notifications_router)
    app.include_router(preferences_router)
    app.include_router(webhooks_router)

    return app


app = create_app()
