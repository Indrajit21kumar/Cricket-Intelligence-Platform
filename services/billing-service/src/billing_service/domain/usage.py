"""Usage metering — exactly-once per period (M03 Step 4, AC-M03-03, NFR-M03-02).

Recording a metered event is idempotent on ``idempotency_key``:

- a durable ``usage_records`` row is inserted with ``ON CONFLICT
  (idempotency_key) DO NOTHING`` — the UNIQUE constraint is the exactly-once
  guarantee (a replayed event inserts nothing).
- ONLY when a new row is inserted do we increment the fast-path Redis
  counter (:mod:`billing_service.domain.usage_counter`), which the
  entitlement check reads. A duplicate leaves both the table and the counter
  untouched.

``usage_records`` is the durable source of truth; the Redis counter is a
cache and can be rebuilt from it via :func:`reconcile_counter` if they ever
drift (e.g. a Redis restart).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import redis.asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from billing_service.domain.usage_counter import get_usage, incr_usage


@dataclass(frozen=True, slots=True)
class UsageResult:
    recorded: bool  # False = duplicate (idempotent no-op)
    total: int  # usage total for the period after this call


async def record_usage(
    session: AsyncSession,
    redis: aioredis.Redis,
    *,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    meter_key: str,
    qty: int,
    idempotency_key: str,
    period: str,
) -> UsageResult:
    """Record a usage event exactly once; increment the counter only on insert."""
    row = (
        await session.execute(
            text(
                "INSERT INTO usage_records "
                "  (id, tenant_id, subscription_id, meter_key, qty, period, "
                "   idempotency_key) "
                "VALUES (:id, :tid, :sub, :meter, :qty, :period, :idem) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "sub": subscription_id,
                "meter": meter_key,
                "qty": qty,
                "period": period,
                "idem": idempotency_key,
            },
        )
    ).first()

    if row is None:
        # Duplicate — exactly-once no-op. Return the current counter value.
        total = await get_usage(
            redis, subscription_id=subscription_id, meter_key=meter_key, period=period
        )
        return UsageResult(recorded=False, total=total)

    total = await incr_usage(
        redis,
        subscription_id=subscription_id,
        meter_key=meter_key,
        period=period,
        qty=qty,
    )
    return UsageResult(recorded=True, total=total)


async def reconcile_counter(
    session: AsyncSession,
    redis: aioredis.Redis,
    *,
    subscription_id: uuid.UUID,
    meter_key: str,
    period: str,
) -> int:
    """Rebuild the Redis counter from the durable usage_records sum.

    Ops/repair path — the table is authoritative; the counter is a cache.
    """
    total = (
        await session.execute(
            text(
                "SELECT COALESCE(SUM(qty), 0) FROM usage_records "
                "WHERE subscription_id = :sub AND meter_key = :meter "
                "AND period = :period"
            ),
            {"sub": subscription_id, "meter": meter_key, "period": period},
        )
    ).scalar() or 0
    from billing_service.domain.usage_counter import _key

    await redis.set(_key(subscription_id, meter_key, period), int(total))
    return int(total)
