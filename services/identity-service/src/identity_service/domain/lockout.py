"""Brute-force login lockout (M02 Step 8, AC-M02-05, NFR-M02-03).

A Redis counter per email. Each failed login increments it (with a rolling
window TTL); once it crosses ``MAX_FAILURES`` the account is locked for
``LOCK_SECONDS`` and further login attempts are rejected before the password
is even checked. A successful login clears the counter.

Keying by email (not IP) defends the account directly. IP-based rate limiting
is a complementary layer added at the gateway (Book 2 Ch. 7).
"""

from __future__ import annotations

import redis.asyncio as aioredis

MAX_FAILURES = 5
WINDOW_SECONDS = 15 * 60  # failures expire after 15 min of no attempts
LOCK_SECONDS = 15 * 60  # lock duration once tripped

_FAIL_PREFIX = "cip:login:fail:"
_LOCK_PREFIX = "cip:login:lock:"


def _norm(email: str) -> str:
    return email.strip().lower()


async def is_locked(redis: aioredis.Redis, email: str) -> bool:
    """True if the account is currently locked out."""
    return bool(await redis.exists(f"{_LOCK_PREFIX}{_norm(email)}"))


async def record_failure(redis: aioredis.Redis, email: str) -> bool:
    """Increment the failure counter; lock + return True if the threshold trips.

    Returns True if this failure caused a lock (or the account was already
    locked), else False.
    """
    key = f"{_FAIL_PREFIX}{_norm(email)}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, WINDOW_SECONDS)
    if count >= MAX_FAILURES:
        await redis.set(f"{_LOCK_PREFIX}{_norm(email)}", "1", ex=LOCK_SECONDS)
        await redis.delete(key)
        return True
    return False


async def clear(redis: aioredis.Redis, email: str) -> None:
    """Clear failure counter + lock on a successful login."""
    await redis.delete(f"{_FAIL_PREFIX}{_norm(email)}", f"{_LOCK_PREFIX}{_norm(email)}")
