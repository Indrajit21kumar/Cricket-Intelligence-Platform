"""Unit tests for :class:`InMemoryIdempotencyStore`.

The Redis-backed variant is covered by the integration suite; the semantics
tested here (first-writer-wins) are identical.
"""

from __future__ import annotations

from cip_events.idempotency import InMemoryIdempotencyStore


class TestFirstWriterWins:
    async def test_first_claim_true(self) -> None:
        store = InMemoryIdempotencyStore()
        assert await store.claim("k1") is True

    async def test_second_claim_false(self) -> None:
        store = InMemoryIdempotencyStore()
        assert await store.claim("k1") is True
        assert await store.claim("k1") is False
        assert await store.claim("k1") is False

    async def test_different_keys_independent(self) -> None:
        store = InMemoryIdempotencyStore()
        assert await store.claim("k1") is True
        assert await store.claim("k2") is True
        assert await store.claim("k1") is False
        assert await store.claim("k2") is False

    async def test_close_resets(self) -> None:
        store = InMemoryIdempotencyStore()
        await store.claim("k1")
        await store.close()
        # After close, seen set is cleared → key can be claimed again.
        # (Real Redis has TTL; InMemory just wipes on close for test isolation.)
        assert await store.claim("k1") is True
