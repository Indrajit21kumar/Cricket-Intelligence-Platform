"""FastAPI entrypoint for the CIP report service.

1. Build service :class:`ServiceSettings`.
2. Install ``cip-core`` middleware + exception handlers.
3. Install ``cip-observability``.
4. In the lifespan, build/stash the runtime :class:`Deps`.
5. Mount routers.

Report + coach routes mount from Step 8, alongside health + version.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from report_service import __version__
from report_service.deps import build_deps, shutdown_deps
from report_service.health import router as health_router
from report_service.health import version_router
from report_service.routes import coach_router, reports_router
from report_service.settings import get_service_settings


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
        title="CIP report-service",
        version=__version__,
        description=(
            "M14 Report Generator / AI Coach. Narrates M13's grounded findings "
            "into a coaching report (scores, findings, metric panels, Legend "
            "comparison, annotated video) and answers player questions through a "
            "RAG-grounded AI Coach that defers rather than fabricates."
        ),
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(reports_router)
    app.include_router(coach_router)

    return app


app = create_app()
