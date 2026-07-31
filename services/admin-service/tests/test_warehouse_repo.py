"""Integration tests for warehouse fact-table writes (M20 Step 1).

Exercises :mod:`admin_service.domain.warehouse_repo` directly against a real
database — the dedupe/routing behaviour the ingestion worker relies on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from admin_service.domain.warehouse_repo import (
    count_revenue_events,
    count_usage_events,
    ingest_envelope,
    insert_revenue_event,
    insert_usage_event,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from cip_events import EventEnvelope

pytestmark = pytest.mark.integration


def _envelope(*, idempotency_key: str, payload: dict | None = None) -> EventEnvelope:
    return EventEnvelope(
        correlation_id=f"corr-{uuid.uuid4().hex[:8]}",
        tenant_id=uuid.uuid4(),
        schema_version="1.0.0",
        idempotency_key=idempotency_key,
        produced_at=datetime.now(UTC),
        payload=payload or {},
    )


class TestInsertUsageEvent:
    async def test_first_insert_returns_true(self, session_factory: async_sessionmaker) -> None:
        envelope = _envelope(idempotency_key=f"video.normalized:{uuid.uuid4().hex}")
        async with admin_session(session_factory) as s:
            inserted = await insert_usage_event(s, topic="video.normalized", envelope=envelope)
        assert inserted is True

    async def test_replayed_event_is_a_no_op(self, session_factory: async_sessionmaker) -> None:
        key = f"pose.keypoints:{uuid.uuid4().hex}"
        envelope = _envelope(idempotency_key=key)
        async with admin_session(session_factory) as s:
            first = await insert_usage_event(s, topic="pose.keypoints", envelope=envelope)
        async with admin_session(session_factory) as s:
            second = await insert_usage_event(s, topic="pose.keypoints", envelope=envelope)
        assert first is True
        assert second is False


class TestInsertRevenueEvent:
    async def test_extracts_amount_and_currency_from_payload(
        self, session_factory: async_sessionmaker
    ) -> None:
        envelope = _envelope(
            idempotency_key=f"invoice.paid:{uuid.uuid4().hex}",
            payload={"amount_minor": 4999, "currency": "USD"},
        )
        async with admin_session(session_factory) as s:
            inserted = await insert_revenue_event(
                s, topic="billing.invoice.paid", envelope=envelope
            )
            row = (
                await s.execute(
                    text(
                        "SELECT amount_minor, currency FROM warehouse.fact_revenue_event "
                        "WHERE dedupe_key = :k"
                    ),
                    {"k": envelope.idempotency_key},
                )
            ).one()
        assert inserted is True
        assert row.amount_minor == 4999
        assert row.currency == "USD"

    async def test_subscription_changed_has_no_amount(
        self, session_factory: async_sessionmaker
    ) -> None:
        """subscription.changed carries no amount — must stay NULL, not error."""
        envelope = _envelope(idempotency_key=f"subscription.changed:{uuid.uuid4().hex}")
        async with admin_session(session_factory) as s:
            inserted = await insert_revenue_event(
                s, topic="billing.subscription.changed", envelope=envelope
            )
        assert inserted is True


class TestIngestEnvelopeRouting:
    async def test_usage_topic_lands_in_usage_fact(
        self, session_factory: async_sessionmaker
    ) -> None:
        envelope = _envelope(idempotency_key=f"shot.classified:{uuid.uuid4().hex}")
        async with admin_session(session_factory) as s:
            before = await count_usage_events(s)
        async with admin_session(session_factory) as s:
            await ingest_envelope(s, topic="shot.classified", envelope=envelope)
        async with admin_session(session_factory) as s:
            after = await count_usage_events(s)
        assert after == before + 1

    async def test_revenue_topic_lands_in_revenue_fact(
        self, session_factory: async_sessionmaker
    ) -> None:
        envelope = _envelope(idempotency_key=f"billing.usage.recorded:{uuid.uuid4().hex}")
        async with admin_session(session_factory) as s:
            before = await count_revenue_events(s)
        async with admin_session(session_factory) as s:
            await ingest_envelope(s, topic="billing.usage.recorded", envelope=envelope)
        async with admin_session(session_factory) as s:
            after = await count_revenue_events(s)
        assert after == before + 1

    async def test_unknown_topic_raises(self, session_factory: async_sessionmaker) -> None:
        envelope = _envelope(idempotency_key=f"unknown:{uuid.uuid4().hex}")
        async with admin_session(session_factory) as s:
            with pytest.raises(ValueError, match="not a warehouse-ingested topic"):
                await ingest_envelope(s, topic="cip.demo.echoed", envelope=envelope)
