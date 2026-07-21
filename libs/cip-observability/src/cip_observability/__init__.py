"""cip-observability — logs, metrics, and tracing keyed by correlation_id.

Public API established in M01 Step 3.

Typical usage from a service's ``main.py``::

    from fastapi import FastAPI
    from cip_core import get_settings, install as install_cip_core
    from cip_observability import configure_all

    app = FastAPI()
    settings = get_settings()
    install_cip_core(app)
    configure_all(settings, app=app)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from cip_core import Settings
from cip_observability import instrumentation, logging, metrics, tracing
from cip_observability.logging import configure as configure_logging
from cip_observability.logging import get_logger
from cip_observability.metrics import configure as configure_metrics
from cip_observability.metrics import get_meter
from cip_observability.tracing import CIPContextSpanProcessor, get_tracer
from cip_observability.tracing import configure as configure_tracing

if TYPE_CHECKING:
    from fastapi import FastAPI

__version__ = "0.1.0"


def configure_all(
    settings: Settings,
    app: FastAPI | None = None,
    *,
    instrument_httpx: bool = True,
    instrument_sqlalchemy: bool = True,
) -> None:
    """One-call setup: logs + traces + metrics + instrumentation.

    Call this once during service startup, after :func:`cip_core.install`
    but before serving traffic. Set ``instrument_sqlalchemy=False`` for
    services that don't use SQLAlchemy (etc).
    """
    configure_logging(settings)
    configure_tracing(settings)
    configure_metrics(settings)
    instrumentation.install(
        app,
        instrument_httpx=instrument_httpx,
        instrument_sqlalchemy=instrument_sqlalchemy,
    )


__all__ = [
    "CIPContextSpanProcessor",
    "__version__",
    "configure_all",
    "configure_logging",
    "configure_metrics",
    "configure_tracing",
    "get_logger",
    "get_meter",
    "get_tracer",
    "instrumentation",
    "logging",
    "metrics",
    "tracing",
]
