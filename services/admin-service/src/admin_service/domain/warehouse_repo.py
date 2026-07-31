"""Warehouse fact-table writes (M20 Step 1, NFR-M20-03).

Every insert is idempotent on ``dedupe_key`` (the event's own
``idempotency_key`` — the same dedup anchor :mod:`cip_events` uses for its
consumer-side dedup), so replaying an event is a safe no-op re-ingest rather
than a duplicate row.

All access goes through ``admin_session`` — these tables carry no RLS (they
are platform-global by nature: a fact belongs to the warehouse, not to a
tenant's row-level scope), consistent with M12's global-table pattern.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_service.domain.ingest import is_revenue_topic, is_usage_topic
from cip_events import EventEnvelope

SCHEMA = "warehouse"


async def ensure_dim_date(session: AsyncSession, occurred_at: datetime) -> None:
    """Idempotently make sure ``dim_date`` has a row for this event's date."""
    day = occurred_at.date()
    _iso_year, iso_week, iso_dow = day.isocalendar()
    await session.execute(
        text(
            # SCHEMA is a module-level constant, never user input.
            f"INSERT INTO {SCHEMA}.dim_date (date, year, month, day, iso_week, iso_dow) "  # nosec B608
            "VALUES (:d, :y, :m, :dd, :wk, :dow) "
            "ON CONFLICT (date) DO NOTHING"
        ),
        {
            "d": day,
            "y": day.year,
            "m": day.month,
            "dd": day.day,
            "wk": iso_week,
            "dow": iso_dow,
        },
    )


async def insert_usage_event(session: AsyncSession, *, topic: str, envelope: EventEnvelope) -> bool:
    """Insert one ``fact_usage_event`` row. Returns True if newly ingested."""
    await ensure_dim_date(session, envelope.produced_at)
    row = (
        await session.execute(
            text(
                f"INSERT INTO {SCHEMA}.fact_usage_event "  # nosec B608 -- SCHEMA is a constant
                "  (id, event_topic, tenant_id, correlation_id, occurred_at, "
                "   dedupe_key, payload) "
                "VALUES (:id, :topic, :tid, :corr, :occurred, :dedupe, cast(:payload as jsonb)) "
                "ON CONFLICT (dedupe_key) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "topic": topic,
                "tid": envelope.tenant_id,
                "corr": envelope.correlation_id,
                "occurred": envelope.produced_at,
                "dedupe": envelope.idempotency_key,
                "payload": json.dumps(envelope.payload, default=str),
            },
        )
    ).first()
    return row is not None


async def insert_revenue_event(
    session: AsyncSession, *, topic: str, envelope: EventEnvelope
) -> bool:
    """Insert one ``fact_revenue_event`` row. Returns True if newly ingested."""
    await ensure_dim_date(session, envelope.produced_at)
    amount_minor = envelope.payload.get("amount_minor")
    currency = envelope.payload.get("currency")
    row = (
        await session.execute(
            text(
                f"INSERT INTO {SCHEMA}.fact_revenue_event "  # nosec B608 -- SCHEMA is a constant
                "  (id, event_topic, tenant_id, occurred_at, dedupe_key, "
                "   amount_minor, currency, payload) "
                "VALUES (:id, :topic, :tid, :occurred, :dedupe, :amt, :cur, "
                "        cast(:payload as jsonb)) "
                "ON CONFLICT (dedupe_key) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "topic": topic,
                "tid": envelope.tenant_id,
                "occurred": envelope.produced_at,
                "dedupe": envelope.idempotency_key,
                "amt": amount_minor,
                "cur": currency,
                "payload": json.dumps(envelope.payload, default=str),
            },
        )
    ).first()
    return row is not None


async def ingest_envelope(session: AsyncSession, *, topic: str, envelope: EventEnvelope) -> bool:
    """Route one envelope to its fact table. Returns True if newly ingested.

    Any topic outside :data:`~admin_service.domain.ingest.ALL_INGESTED_TOPICS`
    is a caller error (the worker only subscribes to those topics), so this
    raises loudly rather than silently dropping an event.
    """
    if is_revenue_topic(topic):
        return await insert_revenue_event(session, topic=topic, envelope=envelope)
    if is_usage_topic(topic):
        return await insert_usage_event(session, topic=topic, envelope=envelope)
    raise ValueError(f"topic {topic!r} is not a warehouse-ingested topic")


async def count_usage_events(session: AsyncSession) -> int:
    """Row count — used by Step 1's schema test to prove ingestion happened."""
    query = f"SELECT count(*) FROM {SCHEMA}.fact_usage_event"  # nosec B608 -- SCHEMA is a constant
    result = await session.execute(text(query))
    return int(result.scalar_one())


async def count_revenue_events(session: AsyncSession) -> int:
    query = f"SELECT count(*) FROM {SCHEMA}.fact_revenue_event"  # nosec B608 -- SCHEMA is a constant
    result = await session.execute(text(query))
    return int(result.scalar_one())
