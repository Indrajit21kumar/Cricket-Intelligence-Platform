"""Structured JSON logging bound to CIP request context and OTel spans.

Every log line carries — automatically, without the caller having to remember:

- ``correlation_id`` from :func:`cip_core.get_correlation_id`
- ``tenant_id``      from :func:`cip_core.get_tenant_id`
- ``trace_id`` and ``span_id`` from the active OpenTelemetry span, if any
- ``service`` name and ``env`` from :class:`cip_core.Settings`

Third-party libraries (FastAPI, SQLAlchemy, aiokafka) log via the stdlib
``logging`` module. :func:`configure` also routes stdlib log records through
the same structlog pipeline so *all* log output — ours and theirs — arrives
as JSON with the same context fields (Book 3 §8).
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from cip_core import Settings, get_correlation_id, get_tenant_id
from opentelemetry import trace
from structlog.typing import EventDict, WrappedLogger


def _add_correlation_id(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Attach the current request's correlation id, if any."""
    cid = get_correlation_id()
    if cid is not None:
        event_dict["correlation_id"] = cid
    return event_dict


def _add_tenant_id(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Attach the current request's tenant id, if any."""
    tid = get_tenant_id()
    if tid is not None:
        event_dict["tenant_id"] = str(tid)
    return event_dict


def _add_otel_span(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Attach the current OTel span's trace_id and span_id, if any."""
    span = trace.get_current_span()
    ctx = span.get_span_context()
    if ctx.is_valid:
        event_dict["trace_id"] = format(ctx.trace_id, "032x")
        event_dict["span_id"] = format(ctx.span_id, "016x")
    return event_dict


def _build_processors(service_name: str, env: str) -> list[structlog.typing.Processor]:
    """The structlog processor chain used for both structlog and stdlib logs."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_correlation_id,
        _add_tenant_id,
        _add_otel_span,
        _static_service_fields(service_name, env),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]


def _static_service_fields(service_name: str, env: str) -> structlog.typing.Processor:
    """Return a processor that stamps every log line with service + env."""

    def _add(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("service", service_name)
        event_dict.setdefault("env", env)
        return event_dict

    return _add


def configure(settings: Settings) -> None:
    """Configure structlog + stdlib logging bridge for a service.

    Idempotent — calling it twice is a no-op the second time (avoids doubling
    the stdlib handler stack when a test suite re-initialises).
    """
    processors = _build_processors(settings.service_name, settings.env)

    # structlog: use its own processors, terminate with JSON.
    structlog.configure(
        processors=[
            *processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level_from_name(settings.log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # stdlib logging: route through structlog's ProcessorFormatter so
    # third-party log records (FastAPI, SQLAlchemy, aiokafka) get the same
    # processors + JSON shape.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    # Replace any pre-existing handlers to avoid duplicated output.
    root.handlers = [handler]
    root.setLevel(_level_from_name(settings.log_level))


def _level_from_name(name: str) -> int:
    """Map a level name (case-insensitive) to a stdlib logging int level."""
    value = logging.getLevelName(name.upper())
    if isinstance(value, int):
        return value
    return logging.INFO


def get_logger(name: str | None = None, **initial_values: Any) -> Any:
    """Return a bound structlog logger."""
    logger = structlog.get_logger(name)
    if initial_values:
        return logger.bind(**initial_values)
    return logger
