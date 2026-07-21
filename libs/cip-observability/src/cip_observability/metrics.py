"""OpenTelemetry metrics setup for CIP services.

Metrics export over OTLP/gRPC to the collector endpoint from
``OTEL_EXPORTER_OTLP_ENDPOINT``. Book 3 §8 requires SLO-driving metrics
per stage; individual services define their own counters/histograms via
:func:`get_meter`.
"""

from __future__ import annotations

import os

from cip_core import Settings
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.sdk.resources import Resource

DEFAULT_OTLP_ENDPOINT = "http://localhost:4317"


def configure(
    settings: Settings,
    *,
    exporter: MetricExporter | None = None,
    export_interval_ms: int = 60_000,
) -> MeterProvider:
    """Install a global :class:`MeterProvider` (last-wins).

    Pass ``exporter`` to override the default OTLP exporter (tests use
    :class:`InMemoryMetricReader`). Calling more than once replaces the
    active provider — production calls once; tests replace per-test.
    """
    resource = Resource.create(
        {
            "service.name": settings.service_name,
            "deployment.environment": settings.env,
        }
    )

    if exporter is None:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", DEFAULT_OTLP_ENDPOINT)
        exporter = OTLPMetricExporter(endpoint=endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(exporter, export_interval_millis=export_interval_ms)
    provider = MeterProvider(resource=resource, metric_readers=[reader])

    metrics.set_meter_provider(provider)
    return provider


def get_meter(name: str) -> metrics.Meter:
    """Return a meter for a module — thin wrapper around ``metrics.get_meter``."""
    return metrics.get_meter(name)
