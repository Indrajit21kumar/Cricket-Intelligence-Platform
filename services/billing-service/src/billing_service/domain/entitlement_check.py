"""Entitlement check with a Redis cache (M03 Step 3, AC-M03-02).

The check answers "is X allowed / how much quota remains?" for a subject:

- flag keys (``feature.*``): allowed iff the plan enables the flag.
- quota keys (``analysis.quota_monthly``): remaining = quota - usage this
  period (usage from the Redis counter); allowed iff remaining > 0 or the
  quota is unlimited (-1).

Caching (NFR-M03-01 <30ms + AC-M03-02 graceful degradation):
- The plan's resolved entitlement map is cached per tenant under a FRESH key
  (short TTL) and a LAST-KNOWN-GOOD key (long TTL).
- On a cache miss we resolve from the DB and refresh both keys.
- If the DB resolve FAILS (provider/datastore outage) we fall back to the
  last-known-good map — the check degrades rather than hard-failing.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

import redis.asyncio as aioredis

from billing_service.domain.entitlements import (
    UNLIMITED,
    is_flag_enabled,
    quota_value,
)
from billing_service.domain.usage_counter import current_period, get_usage

_FRESH_PREFIX = "cip:ent:fresh:"
_LKG_PREFIX = "cip:ent:lkg:"
_FRESH_TTL = 300  # 5 min
_LKG_TTL = 60 * 60 * 24 * 7  # 7 days

# Which meter a quota key draws down.
METER_FOR_QUOTA = {"analysis.quota_monthly": "analysis.consumed"}

# What the cache stores per tenant.
Resolved = dict[str, object]  # {"subscription_id": str, "entitlements": {...}}

# A resolver fetches {subscription_id, entitlements} from the datastore.
Resolver = Callable[[uuid.UUID], Awaitable[Resolved | None]]


@dataclass(frozen=True, slots=True)
class CheckResult:
    allowed: bool
    remaining: int | None  # None for flags; -1 = unlimited
    cached: bool
    degraded: bool = False


async def _load_resolved(
    redis: aioredis.Redis,
    tenant_id: uuid.UUID,
    resolver: Resolver,
) -> tuple[Resolved | None, bool, bool]:
    """Return (resolved, from_cache, degraded)."""
    fresh = await redis.get(f"{_FRESH_PREFIX}{tenant_id}")
    if fresh is not None:
        return json.loads(fresh), True, False

    try:
        resolved = await resolver(tenant_id)
    except Exception:
        lkg = await redis.get(f"{_LKG_PREFIX}{tenant_id}")
        if lkg is not None:
            return json.loads(lkg), True, True
        raise

    if resolved is None:
        return None, False, False

    payload = json.dumps(resolved)
    await redis.set(f"{_FRESH_PREFIX}{tenant_id}", payload, ex=_FRESH_TTL)
    await redis.set(f"{_LKG_PREFIX}{tenant_id}", payload, ex=_LKG_TTL)
    return resolved, False, False


async def check_entitlement(
    redis: aioredis.Redis,
    *,
    tenant_id: uuid.UUID,
    key: str,
    resolver: Resolver,
) -> CheckResult:
    """Resolve + evaluate a single entitlement for a tenant's subscription."""
    resolved, from_cache, degraded = await _load_resolved(redis, tenant_id, resolver)
    if resolved is None:
        # No active subscription -> nothing entitled.
        return CheckResult(allowed=False, remaining=0, cached=from_cache)

    entitlements = cast(dict[str, str], resolved["entitlements"])
    subscription_id = uuid.UUID(str(resolved["subscription_id"]))

    if key.startswith("feature."):
        return CheckResult(
            allowed=is_flag_enabled(entitlements, key),
            remaining=None,
            cached=from_cache,
            degraded=degraded,
        )

    # Quota key.
    quota = quota_value(entitlements, key, default=0)
    if quota == UNLIMITED:
        return CheckResult(allowed=True, remaining=UNLIMITED, cached=from_cache, degraded=degraded)

    meter = METER_FOR_QUOTA.get(key)
    used = 0
    if meter is not None:
        used = await get_usage(
            redis,
            subscription_id=subscription_id,
            meter_key=meter,
            period=current_period(),
        )
    remaining = max(quota - used, 0)
    return CheckResult(
        allowed=remaining > 0,
        remaining=remaining,
        cached=from_cache,
        degraded=degraded,
    )


def invalidate_keys(tenant_id: uuid.UUID) -> list[str]:
    """Cache keys to delete when a tenant's subscription/plan changes."""
    return [f"{_FRESH_PREFIX}{tenant_id}"]
