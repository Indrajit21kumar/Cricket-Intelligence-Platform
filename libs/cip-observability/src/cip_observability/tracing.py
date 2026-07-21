"""OpenTelemetry tracing setup for CIP services.

Configures a global :class:`TracerProvider` that exports spans over OTLP/gRPC
to the collector endpoint from the environment (``OTEL_EXPORTER_OTLP_ENDPOINT``,
defaulting to the local ``docker-compose`` collector at
``http://localhost:4317``).

Every span produced through this provider is automatically stamped with
``cip.correlation_id`` and ``cip.tenant_id`` from :mod:`cip_core.context`
by a custom :class:`SpanProcessor` — so trace attributes and log entries
share the same identifiers (Book 3 §8).
"""

from __future__ import annotations

import os
from typing import Any

from cip_core import Settings, get_correlation_id, get_tenant_id
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter

DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"


class CIPContextSpanProcessor(SpanProcessor):
    """Stamp every started span with the current CIP request context.

    Runs on ``on_start`` so attributes appear on the span from the moment it
    is created — no export delay, no missed early spans.
    """

    def on_start(self, span: Span, parent_context: Any = None) -> None:
        cid = get_correlation_id()
        if cid is not None:
            span.set_attribute("cip.correlation_id", cid)
        tid = get_tenant_id()
        if tid is not None:
            span.set_attribute("cip.tenant_id", str(tid))

    def on_end(self, span: ReadableSpan) -> None:
        # no-op — export is handled by the batch processor
        pass

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


def configure(
    settings: Settings,
    *,
    exporter: SpanExporter | None = None,
) -> TracerProvider:
    """Install a global :class:`TracerProvider` (last-wins).

    Pass ``exporter`` to override the default OTLP exporter (tests use
    :class:`InMemorySpanExporter`). Calling this more than once in a process
    is legal — the most recent call becomes the active provider. In production
    it is called exactly once during service startup; tests use the replace
    behaviour to install a per-test in-memory exporter.
    """
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(CIPContextSpanProcessor())

    if exporter is None:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return provider


def get_tracer(name: str) -> trace.Tracer:
    """Return a tracer for a module — thin wrapper around ``trace.get_tracer``."""
    return trace.get_tracer(name)
