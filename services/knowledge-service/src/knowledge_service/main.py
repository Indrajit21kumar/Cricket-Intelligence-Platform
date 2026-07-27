"""FastAPI entrypoint for the CIP knowledge service.

Every CIP service follows this shape:

1. Build service :class:`ServiceSettings` (env + secret store).
2. Install ``cip-core`` middleware + exception handlers on the FastAPI app.
3. Install ``cip-observability`` (logs + traces + metrics + FastAPI/SQLAlchemy
   instrumentation).
4. In the lifespan, build the runtime :class:`Deps` (DB engine, event bus,
   idempotency store) and stash them on ``app.state``. Shut them down on exit.
5. Mount routers.

In Step 1 the service exposes only the health + version surface so the CI gate
sequence has a real service to test against; the authoring + serving routes are
mounted from Step 3 on.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

import cip_core
import cip_observability
from knowledge_service import __version__
from knowledge_service.deps import build_deps, shutdown_deps
from knowledge_service.health import router as health_router
from knowledge_service.health import version_router
from knowledge_service.routes import internal_router, kg_router
from knowledge_service.settings import get_service_settings


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
        title="CIP knowledge-service",
        version=__version__,
        description=(
            "M12 Cricket Knowledge Graph. A governed, versioned store of coaching "
            "rules (Fault->Cause->Risk->Drill) and the ontology behind them, served "
            "to M13 (reasoning) and M14 (RAG grounding)."
        ),
        lifespan=lifespan,
    )

    cip_core.install(app)
    cip_observability.configure_all(settings, app=app)

    app.include_router(health_router)
    app.include_router(version_router)
    app.include_router(kg_router)
    app.include_router(internal_router)

    return app


app = create_app()
