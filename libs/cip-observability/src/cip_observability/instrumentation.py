"""One-call auto-instrumentation of the runtime the services actually use.

Wires OpenTelemetry auto-instrumentors for FastAPI, SQLAlchemy, and httpx —
the three libraries every CIP service touches on the request path. The
instrumentors are idempotent; call :func:`install` on service startup.

All library imports are deferred inside :func:`install` so cip-observability
does not force FastAPI / SQLAlchemy / httpx onto every consumer at
package-import time. Services that use, say, only FastAPI can install just
that instrumentor without needing SQLAlchemy or httpx installed. This is
the correct dependency shape for a monorepo where different services touch
different subsets of the stack.

The aiokafka producer/consumer used by :mod:`cip_events` do not have a
mature OTel auto-instrumentor yet, so span context is propagated through
event envelopes explicitly at that layer (Step 5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

_httpx_instrumented = False
_sqlalchemy_instrumented = False
_fastapi_instrumented_apps: set[int] = set()


def install(
    app: FastAPI | None = None,
    *,
    instrument_httpx: bool = True,
    instrument_sqlalchemy: bool = True,
) -> None:
    """Enable auto-instrumentation for the app's runtime dependencies.

    Pass a FastAPI ``app`` to instrument its middleware stack. Set
    ``instrument_httpx=False`` or ``instrument_sqlalchemy=False`` for
    services that do not have those libraries installed. Guarded against
    double-installation so tests and reload cycles are safe.
    """
    global _httpx_instrumented, _sqlalchemy_instrumented

    if app is not None and id(app) not in _fastapi_instrumented_apps:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
        _fastapi_instrumented_apps.add(id(app))

    if instrument_httpx and not _httpx_instrumented:
        try:
            # Imported at call time so this lib doesn't require httpx-instrumentor
            # to be installed; services that use httpx pull it in themselves.
            from opentelemetry.instrumentation.httpx import (  # type: ignore[import-not-found]
                HTTPXClientInstrumentor,
            )
        except ImportError:
            pass
        else:
            HTTPXClientInstrumentor().instrument()
            _httpx_instrumented = True

    if instrument_sqlalchemy and not _sqlalchemy_instrumented:
        try:
            from opentelemetry.instrumentation.sqlalchemy import (  # type: ignore[import-not-found]
                SQLAlchemyInstrumentor,
            )
        except ImportError:
            pass
        else:
            SQLAlchemyInstrumentor().instrument()
            _sqlalchemy_instrumented = True
