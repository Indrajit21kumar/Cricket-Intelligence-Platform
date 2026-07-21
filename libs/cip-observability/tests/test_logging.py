"""Tests for :mod:`cip_observability.logging`.

Verifies that every log line automatically carries the CIP request context
(correlation_id, tenant_id) and — when a span is active — the OTel trace_id
and span_id, all in JSON. This is Book 3 §8 by construction: no caller has
to remember to include those fields.
"""

from __future__ import annotations

import io
import json
import logging as stdlib_logging
import uuid
from contextlib import redirect_stdout

from cip_core import Settings, correlation_scope, tenant_scope
from cip_observability.logging import configure, get_logger


def _run_and_capture(func: object, *, settings: Settings) -> list[dict[str, object]]:
    """Run ``func`` under a configured logger and return the captured JSON lines."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        configure(settings)
        func()  # type: ignore[operator]
    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


class TestBaseFields:
    def test_log_includes_service_and_env(self, settings: Settings) -> None:
        def act() -> None:
            get_logger().info("hello")

        records = _run_and_capture(act, settings=settings)
        assert len(records) == 1
        rec = records[0]
        assert rec["service"] == "test-service"
        assert rec["env"] == "dev"
        assert rec["level"] == "info"
        assert rec["event"] == "hello"
        assert "timestamp" in rec

    def test_no_context_omits_ids(self, settings: Settings) -> None:
        def act() -> None:
            get_logger().info("bare")

        records = _run_and_capture(act, settings=settings)
        assert "correlation_id" not in records[0]
        assert "tenant_id" not in records[0]
        assert "trace_id" not in records[0]


class TestContextBinding:
    def test_correlation_id_appears(self, settings: Settings) -> None:
        def act() -> None:
            with correlation_scope("abc-123"):
                get_logger().info("with-corr")

        records = _run_and_capture(act, settings=settings)
        assert records[0]["correlation_id"] == "abc-123"

    def test_tenant_id_appears(self, settings: Settings) -> None:
        tid = uuid.uuid4()

        def act() -> None:
            with tenant_scope(tid):
                get_logger().info("with-tenant")

        records = _run_and_capture(act, settings=settings)
        assert records[0]["tenant_id"] == str(tid)

    def test_both_ids_appear_together(self, settings: Settings) -> None:
        tid = uuid.uuid4()

        def act() -> None:
            with correlation_scope("c1"), tenant_scope(tid):
                get_logger().info("with-both")

        records = _run_and_capture(act, settings=settings)
        assert records[0]["correlation_id"] == "c1"
        assert records[0]["tenant_id"] == str(tid)


class TestStdlibBridge:
    """Third-party libraries log through stdlib; those records MUST also be
    JSON-formatted with our context fields, so ops has one grep-able stream."""

    def test_stdlib_logger_produces_json(self, settings: Settings) -> None:
        def act() -> None:
            with correlation_scope("stdlib-1"):
                stdlib_logging.getLogger("fake.thirdparty").info("hi from stdlib")

        records = _run_and_capture(act, settings=settings)
        assert any(
            rec.get("event") == "hi from stdlib" and rec.get("correlation_id") == "stdlib-1"
            for rec in records
        )

    def test_stdlib_level_maps(self, settings: Settings) -> None:
        settings_copy = settings.model_copy(update={"log_level": "DEBUG"})

        def act() -> None:
            stdlib_logging.getLogger("test").debug("debug-msg")

        records = _run_and_capture(act, settings=settings_copy)
        assert any(rec.get("level") == "debug" for rec in records)
