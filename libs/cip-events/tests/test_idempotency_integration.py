"""Integration tests for :class:`RedisIdempotencyStore` (needs local Redis)."""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio

from cip_events.idempotency import RedisIdempotencyStore

pytestmark = pytest.mark.integration

DEFAULT_URL = "redis://localhost:6379/0"


def _redis_url() -> str:
    return os.environ.get("CIP_REDIS_URL", DEFAULT_URL)


@pytest_asyncio.fixture
async def store() -> RedisIdempotencyStore:
    s = RedisIdempotencyStore(_redis_url())
    yield s
    await s.close()


class TestRedisFirstWriterWins:
    async def test_first_claim_true_second_false(self, store: RedisIdempotencyStore) -> None:
        key = f"test-{uuid.uuid4()}"
        assert await store.claim(key) is True
        assert await store.claim(key) is False

    async def test_ttl_expiry(self, store: RedisIdempotencyStore) -> None:
        """A key claimed with ttl=1 should be reclaimable after ~1 second."""
        import asyncio

        key = f"test-ttl-{uuid.uuid4()}"
        assert await store.claim(key, ttl_seconds=1) is True
        assert await store.claim(key, ttl_seconds=1) is False
        await asyncio.sleep(1.2)
        assert await store.claim(key, ttl_seconds=1) is True
