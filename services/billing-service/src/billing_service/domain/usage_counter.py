"""Redis usage counters — the fast path for quota-remaining (M03 Steps 3-4).

Metered usage is counted in Redis per (subscription, meter_key, period) so the
entitlement check can compute ``remaining = quota - usage`` without a DB read
(NFR-M03-01 <30ms). Step 4's metering increments this counter (and persists
a durable ``usage_records`` row for audit/reconciliation). The counter TTLs a
little past the period so old buckets self-expire.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import redis.asyncio as aioredis

_PREFIX = "cip:usage:"
# Keep a period's counter ~40 days so a monthly bucket survives the whole month.
_TTL_SECONDS = 60 * 60 * 24 * 40


def current_period(now: datetime | None = None) -> str:
    """Return the current billing period bucket as ``YYYY-MM`` (UTC)."""
    dt = now or datetime.now(UTC)
    return f"{dt.year:04d}-{dt.month:02d}"


def _key(subscription_id: uuid.UUID, meter_key: str, period: str) -> str:
    return f"{_PREFIX}{subscription_id}:{meter_key}:{period}"


async def get_usage(
    redis: aioredis.Redis,
    *,
    subscription_id: uuid.UUID,
    meter_key: str,
    period: str,
) -> int:
    """Return the counted usage for the bucket (0 if none)."""
    raw = await redis.get(_key(subscription_id, meter_key, period))
    return int(raw) if raw is not None else 0


async def incr_usage(
    redis: aioredis.Redis,
    *,
    subscription_id: uuid.UUID,
    meter_key: str,
    period: str,
    qty: int = 1,
) -> int:
    """Increment + return the new count. Sets TTL on first write."""
    key = _key(subscription_id, meter_key, period)
    new_value = await redis.incrby(key, qty)
    if new_value == qty:  # first write in this bucket
        await redis.expire(key, _TTL_SECONDS)
    return int(new_value)
