"""Entitlement-check + cache tests (M03 Step 3, AC-M03-02, NFR-M03-01).

Uses the real Redis (from docker-compose / CI) for the cache + usage counter.
Covers: flag checks, quota remaining, unlimited, cache hit, <30ms warm, and
graceful degradation to last-known-good when the resolver fails.
"""

from __future__ import annotations

import os
import time
import uuid

import pytest
import pytest_asyncio
import redis.asyncio as aioredis

from billing_service.domain.entitlement_check import Resolved, check_entitlement
from billing_service.domain.usage_counter import current_period, incr_usage

pytestmark = pytest.mark.integration


def _redis_url() -> str:
    return os.environ.get("CIP_REDIS_URL", "redis://localhost:6379/0")


@pytest_asyncio.fixture
async def redis():
    client = aioredis.from_url(_redis_url(), decode_responses=True)
    yield client
    await client.aclose()


def _resolver_for(subscription_id: uuid.UUID, entitlements: dict[str, str]):
    async def _resolve(_tenant_id: uuid.UUID) -> Resolved | None:
        return {"subscription_id": str(subscription_id), "entitlements": entitlements}

    return _resolve


class TestFlagChecks:
    async def test_enabled_flag_allowed(self, redis) -> None:
        tid = uuid.uuid4()
        res = await check_entitlement(
            redis,
            tenant_id=tid,
            key="feature.ai_coach",
            resolver=_resolver_for(uuid.uuid4(), {"feature.ai_coach": "true"}),
        )
        assert res.allowed is True
        assert res.remaining is None

    async def test_disabled_flag_denied(self, redis) -> None:
        tid = uuid.uuid4()
        res = await check_entitlement(
            redis,
            tenant_id=tid,
            key="feature.partner_api",
            resolver=_resolver_for(uuid.uuid4(), {"feature.partner_api": "false"}),
        )
        assert res.allowed is False


class TestQuotaChecks:
    async def test_quota_remaining_decrements_with_usage(self, redis) -> None:
        tid = uuid.uuid4()
        sub = uuid.uuid4()
        ents = {"analysis.quota_monthly": "5"}

        # No usage yet -> full quota remaining.
        first = await check_entitlement(
            redis,
            tenant_id=tid,
            key="analysis.quota_monthly",
            resolver=_resolver_for(sub, ents),
        )
        assert first.allowed is True
        assert first.remaining == 5

        # Consume 5 -> remaining 0, denied.
        await incr_usage(
            redis,
            subscription_id=sub,
            meter_key="analysis.consumed",
            period=current_period(),
            qty=5,
        )
        after = await check_entitlement(
            redis,
            tenant_id=tid,
            key="analysis.quota_monthly",
            resolver=_resolver_for(sub, ents),
        )
        assert after.remaining == 0
        assert after.allowed is False

    async def test_unlimited_quota(self, redis) -> None:
        tid = uuid.uuid4()
        res = await check_entitlement(
            redis,
            tenant_id=tid,
            key="analysis.quota_monthly",
            resolver=_resolver_for(uuid.uuid4(), {"analysis.quota_monthly": "-1"}),
        )
        assert res.allowed is True
        assert res.remaining == -1

    async def test_no_subscription_denies(self, redis) -> None:
        async def _none(_t: uuid.UUID) -> Resolved | None:
            return None

        res = await check_entitlement(
            redis, tenant_id=uuid.uuid4(), key="feature.ai_coach", resolver=_none
        )
        assert res.allowed is False


class TestCacheBehaviour:
    async def test_second_call_is_cached_and_fast(self, redis) -> None:
        tid = uuid.uuid4()
        calls = {"n": 0}

        async def _counting_resolver(_t: uuid.UUID) -> Resolved | None:
            calls["n"] += 1
            return {
                "subscription_id": str(uuid.uuid4()),
                "entitlements": {"feature.ai_coach": "true"},
            }

        first = await check_entitlement(
            redis, tenant_id=tid, key="feature.ai_coach", resolver=_counting_resolver
        )
        assert first.cached is False

        start = time.perf_counter()
        second = await check_entitlement(
            redis, tenant_id=tid, key="feature.ai_coach", resolver=_counting_resolver
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert second.cached is True
        assert calls["n"] == 1  # resolver not called again
        # NFR-M03-01: warm check < 30ms.
        assert elapsed_ms < 30, f"warm check took {elapsed_ms:.1f}ms"

    async def test_degrades_to_last_known_good_on_resolver_failure(self, redis) -> None:
        tid = uuid.uuid4()

        # First, a good resolve seeds the LKG cache.
        await check_entitlement(
            redis,
            tenant_id=tid,
            key="feature.ai_coach",
            resolver=_resolver_for(uuid.uuid4(), {"feature.ai_coach": "true"}),
        )
        # Expire the FRESH key so the next call must re-resolve.
        await redis.delete(f"cip:ent:fresh:{tid}")

        async def _boom(_t: uuid.UUID) -> Resolved | None:
            raise RuntimeError("datastore down")

        res = await check_entitlement(redis, tenant_id=tid, key="feature.ai_coach", resolver=_boom)
        # Served from last-known-good rather than hard-failing.
        assert res.allowed is True
        assert res.degraded is True

    async def test_no_lkg_and_resolver_fails_raises(self, redis) -> None:
        tid = uuid.uuid4()
        await redis.delete(f"cip:ent:fresh:{tid}", f"cip:ent:lkg:{tid}")

        async def _boom(_t: uuid.UUID) -> Resolved | None:
            raise RuntimeError("datastore down")

        with pytest.raises(RuntimeError):
            await check_entitlement(redis, tenant_id=tid, key="feature.ai_coach", resolver=_boom)
