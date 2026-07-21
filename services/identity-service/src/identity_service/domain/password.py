"""Argon2id password hashing.

Book 3 §5.1: "strong adaptive algorithm". OWASP's current recommendation
is argon2id with parameters roughly: memory 46 MiB minimum (we use 64),
iterations 1-3, parallelism 1. These map to the constants below.

We NEVER log passwords or hashes. Cleanup:

- Register only takes `password: SecretStr` at the API boundary so pydantic
  redacts it in logs and reprs.
- Hasher never accepts a plain str for the raw password without an
  explicit ``str.encode`` — see :meth:`Hasher.hash`.
"""

from __future__ import annotations

from argon2 import PasswordHasher, Type
from argon2.exceptions import VerifyMismatchError

MEMORY_COST_KIB = 65_536  # 64 MiB
TIME_COST = 3
PARALLELISM = 1
HASH_LEN = 32
SALT_LEN = 16


class Hasher:
    """Thin wrapper around argon2-cffi tuned per OWASP + Book 3 §5.1."""

    def __init__(self) -> None:
        self._ph = PasswordHasher(
            time_cost=TIME_COST,
            memory_cost=MEMORY_COST_KIB,
            parallelism=PARALLELISM,
            hash_len=HASH_LEN,
            salt_len=SALT_LEN,
            type=Type.ID,
        )

    def hash(self, password: str) -> str:
        """Return an encoded argon2id hash for ``password``.

        Includes the algorithm identifier, cost parameters, salt, and hash
        in one self-describing string (the ``$argon2id$v=19$m=65536,t=3,p=1$...``
        format). Store as-is; :meth:`verify` re-parses everything from it.
        """
        return self._ph.hash(password)

    def verify(self, encoded_hash: str, password: str) -> bool:
        """Return True iff ``password`` matches ``encoded_hash``.

        Constant-time internally; safe against timing attacks. Returns
        False rather than raising so callers can uniformly convert to
        an authentication failure without leaking whether the account
        exists or the password was wrong.
        """
        try:
            self._ph.verify(encoded_hash, password)
        except VerifyMismatchError:
            return False
        return True

    def needs_rehash(self, encoded_hash: str) -> bool:
        """True if the hash was made with weaker parameters than current.

        Call after a successful verify(); if True, rehash and store. Lets
        us tighten the cost parameters over time without invalidating
        existing sessions.
        """
        # argon2-cffi's return isn't typed; bool() coerces + asserts intent.
        return bool(self._ph.check_needs_rehash(encoded_hash))
