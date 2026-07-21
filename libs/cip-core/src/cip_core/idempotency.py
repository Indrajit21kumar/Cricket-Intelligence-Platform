"""Idempotency-Key extraction (Book 3 §3.1).

The header value is passed through to caller code. Storage-side dedup is
implemented in :mod:`cip_events` (for event handlers) and in future request
middleware (for HTTP mutations, added when the first mutating endpoint lands).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Header

from cip_core.errors import BadRequest

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_KEY_LENGTH = 200


def idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> str | None:
    """FastAPI dependency that returns the ``Idempotency-Key`` header value.

    Returns ``None`` when the header is absent. Raises :class:`BadRequest`
    when it is present but empty or exceeds ``MAX_KEY_LENGTH`` — an idempotency
    contract violation must fail fast, not silently deduplicate under an
    ambiguous key.
    """
    if idempotency_key is None:
        return None
    if idempotency_key == "":
        raise BadRequest("Idempotency-Key header must not be empty")
    if len(idempotency_key) > MAX_KEY_LENGTH:
        raise BadRequest(
            "Idempotency-Key header too long",
            details={"max_length": MAX_KEY_LENGTH, "actual": len(idempotency_key)},
        )
    return idempotency_key


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias=IDEMPOTENCY_HEADER)] = None,
) -> str:
    """Same as :func:`idempotency_key` but 400s when the header is absent.

    Use on endpoints where Book 3 §3.1 mandates idempotency (any POST/PUT/PATCH
    that mutates persistent state or triggers a side effect).
    """
    key = idempotency_key
    if key is None:
        raise BadRequest("Idempotency-Key header is required for this endpoint")
    if key == "":
        raise BadRequest("Idempotency-Key header must not be empty")
    if len(key) > MAX_KEY_LENGTH:
        raise BadRequest(
            "Idempotency-Key header too long",
            details={"max_length": MAX_KEY_LENGTH, "actual": len(key)},
        )
    return key
