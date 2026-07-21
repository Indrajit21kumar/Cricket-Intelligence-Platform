"""Tests for :mod:`cip_observability.metrics`.

OTel refuses to overwrite a MeterProvider once set (same design as tracing),
and MeterProvider does not expose ``resource`` as a public attribute in this
SDK version. So these tests exercise only :func:`get_meter` — a thin
passthrough — and confirm counters/histograms can be created and recorded
against without raising. Resource propagation is covered by the tracing
suite (:mod:`tests.test_tracing`).
"""

from __future__ import annotations

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import Resource

from cip_core import Settings
from cip_observability.metrics import get_meter


class TestGetMeter:
    def test_creates_counter(self, settings: Settings) -> None:
        meter = get_meter("cip.tests")
        counter = meter.create_counter(
            "cip.test.hits",
            description="test-only counter",
        )
        counter.add(1, {"route": "/health/live"})

    def test_creates_histogram(self, settings: Settings) -> None:
        meter = get_meter("cip.tests")
        histogram = meter.create_histogram(
            "cip.test.latency",
            unit="ms",
            description="test-only histogram",
        )
        histogram.record(42.0, {"stage": "unit"})


class TestConstructMeterProvider:
    """MeterProvider can be built directly with a resource for direct inspection."""

    def test_can_build_provider_with_resource_and_reader(self, settings: Settings) -> None:
        resource = Resource.create(
            {
                "service.name": settings.service_name,
                "deployment.environment": settings.env,
            }
        )
        reader = InMemoryMetricReader()
        provider = MeterProvider(resource=resource, metric_readers=[reader])
        # Constructing did not raise; provider is usable.
        assert provider is not None
