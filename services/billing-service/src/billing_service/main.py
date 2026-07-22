"""FastAPI entrypoint for the CIP billing-service (M03).

Wires cip-core middleware, cip-observability, lifespan-managed Deps, seeds
the plan catalogue on startup (idempotent), and mounts the billing routers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from billing_service import __version__
from billing_service.deps import build_deps, shutdown_deps
from billing_service.domain.catalogue import seed_catalogue
from billing_service.health import router as health_router
from billing_service.health import version_router
from billing_service.routes import (
    entitlements_router,
    invoices_router,
    plans_router,
    seats_router,
    subscriptions_router,
    usage_router,
    webhooks_router,
)
from billing_service.settings import get_service_settings
from cip_data import admin_session


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_service_settings()
    deps = await build_deps(settings)
    app.state.deps = deps
    # Seed the plan catalogue (idempotent) so GET /v1/plans works on a fresh DB.
    async with admin_session(deps.session_factory) as session:
        await seed_catalogue(session)
    try:
        yield
    finally:
        await shutdown_deps(deps)


def create_app() -> FastAPI:
    """Factory — importable for tests + ASGI servers."""
    settings = get_service_settings()

    app = FastAPI(
        title="CIP billing-service",
        version=__version__,
        description="Subscription & Billing (M03).",
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(plans_router)
    app.include_router(entitlements_router)
    app.include_router(usage_router)
    app.include_router(subscriptions_router)
    app.include_router(webhooks_router)
    app.include_router(invoices_router)
    app.include_router(seats_router)

    return app


app = create_app()
