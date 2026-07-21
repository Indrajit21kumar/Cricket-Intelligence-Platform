"""Verification / reset token generation.

Tokens are cryptographically random, URL-safe, and NEVER stored in the DB
as-is. Only the SHA-256 hash of the token is persisted (in ``tokens.token_hash``);
a leaked DB dump therefore cannot be replayed against the verification
endpoint.

The raw token is returned to the caller once (in the email or, in M02 dev,
the log line) and then discarded from the process's memory.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

TOKEN_BYTES = 32  # 256 bits of entropy — plenty for a one-time link
DEFAULT_TTL = timedelta(hours=24)


def new_verification_token() -> str:
    """Return a fresh URL-safe token — ~43 characters."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(raw: str) -> str:
    """Return the storage form of ``raw`` (hex SHA-256)."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def expires_at(*, ttl: timedelta = DEFAULT_TTL) -> datetime:
    """Return the expiry timestamp for a newly-issued token."""
    return datetime.now(UTC) + ttl
