"""Unit tests for :mod:`identity_service.domain.password`."""

from __future__ import annotations

import pytest

from identity_service.domain.password import Hasher


class TestHash:
    def test_hash_and_verify_ok(self) -> None:
        h = Hasher()
        encoded = h.hash("correct horse battery staple")
        assert h.verify(encoded, "correct horse battery staple") is True

    def test_wrong_password_verify_false(self) -> None:
        h = Hasher()
        encoded = h.hash("s3cret-passphrase")
        assert h.verify(encoded, "not-the-password") is False

    def test_hash_is_argon2id_encoded(self) -> None:
        encoded = Hasher().hash("hunter2")
        assert encoded.startswith("$argon2id$")

    def test_two_hashes_of_same_password_differ(self) -> None:
        h = Hasher()
        assert h.hash("same-password") != h.hash("same-password")

    def test_needs_rehash_false_for_current_params(self) -> None:
        h = Hasher()
        encoded = h.hash("some-password")
        assert h.needs_rehash(encoded) is False

    @pytest.mark.parametrize("bad", ["", " ", "\x00null-byte"])
    def test_verify_handles_odd_inputs(self, bad: str) -> None:
        h = Hasher()
        encoded = h.hash("real-password")
        assert h.verify(encoded, bad) is False
