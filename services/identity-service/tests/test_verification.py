"""Unit tests for :mod:`identity_service.domain.verification`."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from identity_service.domain.verification import (
    DEFAULT_TTL,
    expires_at,
    hash_token,
    new_verification_token,
)


class TestNewVerificationToken:
    def test_url_safe(self) -> None:
        token = new_verification_token()
        # url-safe = only [A-Za-z0-9_-]
        assert all(c.isalnum() or c in "-_" for c in token)

    def test_high_entropy(self) -> None:
        tokens = {new_verification_token() for _ in range(100)}
        assert len(tokens) == 100  # no collisions in 100 draws

    def test_length_is_deterministic(self) -> None:
        # secrets.token_urlsafe(32) yields ~43 chars (32 bytes -> base64)
        assert 40 <= len(new_verification_token()) <= 50


class TestHashToken:
    def test_stable_for_same_input(self) -> None:
        assert hash_token("abc") == hash_token("abc")

    def test_differs_for_different_input(self) -> None:
        assert hash_token("abc") != hash_token("abcd")

    def test_hex_sha256_length(self) -> None:
        assert len(hash_token("anything")) == 64


class TestExpiresAt:
    def test_default_ttl_24_hours(self) -> None:
        now = datetime.now(UTC)
        exp = expires_at()
        assert abs((exp - now) - DEFAULT_TTL) < timedelta(seconds=2)

    def test_custom_ttl_honoured(self) -> None:
        now = datetime.now(UTC)
        exp = expires_at(ttl=timedelta(hours=1))
        assert abs((exp - now) - timedelta(hours=1)) < timedelta(seconds=2)
