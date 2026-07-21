"""Tests for :mod:`cip_observability.tracing`.

OpenTelemetry's global TracerProvider can only be set once per process
(``trace.set_tracer_provider`` warns and refuses on the second call). So
these tests exercise the interesting logic — :class:`CIPContextSpanProcessor`
and :func:`configure`'s resource construction — via freshly built providers
that we drive directly, not the global one. Behavioural end-to-end
verification (spans emerging from a real request path with correct attrs)
is done in the reference-service integration tests in Step 6.
"""

from __future__ import annotations

import uuid

from cip_core import Settings, correlation_scope, tenant_scope
from cip_observability.tracing import CIPContextSpanProcessor, configure
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def _new_provider_with_exporter(
    settings: Settings,
) -> tuple[TracerProvider, InMemorySpanExporter]:
    """Return a fresh TracerProvider wired to an in-memory exporter."""
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": settings.env,
        }
    )
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(CIPContextSpanProcessor())
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


class TestCIPContextSpanProcessor:
    def test_span_gets_correlation_id_attribute(self, settings: Settings) -> None:
        provider, exporter = _new_provider_with_exporter(settings)
        tracer = provider.get_tracer("test")

        with correlation_scope("corr-42"), tracer.start_as_current_span("op"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes is not None
        assert spans[0].attributes["cip.correlation_id"] == "corr-42"

    def test_span_gets_tenant_id_attribute(self, settings: Settings) -> None:
        provider, exporter = _new_provider_with_exporter(settings)
        tracer = provider.get_tracer("test")
        tid = uuid.uuid4()

        with tenant_scope(tid), tracer.start_as_current_span("op"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].attributes is not None
        assert spans[0].attributes["cip.tenant_id"] == str(tid)

    def test_span_gets_both_attributes(self, settings: Settings) -> None:
        provider, exporter = _new_provider_with_exporter(settings)
        tracer = provider.get_tracer("test")
        tid = uuid.uuid4()

        with (
            correlation_scope("c1"),
            tenant_scope(tid),
            tracer.start_as_current_span("op"),
        ):
            pass

        spans = exporter.get_finished_spans()
        assert spans[0].attributes["cip.correlation_id"] == "c1"
        assert spans[0].attributes["cip.tenant_id"] == str(tid)

    def test_span_without_context_omits_cip_attributes(self, settings: Settings) -> None:
        provider, exporter = _new_provider_with_exporter(settings)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("op"):
            pass

        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        attrs = spans[0].attributes or {}
        assert "cip.correlation_id" not in attrs
        assert "cip.tenant_id" not in attrs


class TestConfigureResource:
    def test_provider_resource_carries_service_and_env(self, settings: Settings) -> None:
        # configure() builds a provider from the same Resource we test here;
        # even if OTel's global provider was already set by an earlier test,
        # the RETURNED provider still has our attributes.
        provider = configure(settings, exporter=InMemorySpanExporter())
        assert provider.resource.attributes["service.name"] == "test-service"
        assert provider.resource.attributes["deployment.environment"] == "dev"
