"""Idempotency store — first-writer-wins for ``idempotency_key``.

The store's ``claim(key)`` returns True the first time it sees a key,
False on every subsequent call within the TTL window. Consumers gate
side effects on that first-True — same event delivered N times → 1 effect
(Book 2 §4.2).

Implementations MUST be atomic (compare-and-set at the store) so two
concurrent consumers processing the same key don't both see True. Redis'
``SET key value NX EX ttl`` is atomic; that's how :class:`RedisIdempotencyStore`
implements it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import redis.asyncio as aioredis

DEFAULT_TTL_SECONDS = 60 * 60 * 24 * 7  # one week


@runtime_checkable
class IdempotencyStore(Protocol):
    """Contract for any dedup backend (Redis today, DynamoDB / Firestore later)."""

    async def claim(self, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        """Return True on the FIRST call for ``key`` within the TTL, else False."""
        ...

    async def close(self) -> None:
        """Release the underlying connection(s)."""
        ...


class RedisIdempotencyStore:
    """Redis-backed :class:`IdempotencyStore` using ``SET NX EX``.

    Keys are namespaced under ``cip:idem:`` so they don't collide with other
    Redis usage (rate limits, sessions).
    """

    KEY_PREFIX = "cip:idem:"

    def __init__(self, url: str) -> None:
        self._client: aioredis.Redis = aioredis.from_url(url, decode_responses=True)

    async def claim(self, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        # SET NX = "only set if not already present" — atomic at the Redis
        # server. First writer gets True; every subsequent SET NX returns None.
        result = await self._client.set(self._namespaced(key), "1", nx=True, ex=ttl_seconds)
        return result is True

    async def close(self) -> None:
        await self._client.aclose()

    def _namespaced(self, key: str) -> str:
        return f"{self.KEY_PREFIX}{key}"


class InMemoryIdempotencyStore:
    """Test-only :class:`IdempotencyStore`. Not thread-safe. Not for production.

    Kept in this module rather than tests/ so consumer tests can import it
    without a tests-package importable path.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    async def claim(self, key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
        if key in self._seen:
            return False
        self._seen.add(key)
        return True

    async def close(self) -> None:
        self._seen.clear()
