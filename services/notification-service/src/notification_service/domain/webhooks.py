"""Provider webhook signature verification (M19 Step 6, §10/§11).

Standard HMAC-SHA256 over the raw request body — the same
``X-CIP-Signature: sha256=<hex>`` convention billing-service's payment
webhook already established (verified against the raw body, not the
parsed JSON, so a reformatting proxy can't silently invalidate a
signature). Reimplemented here rather than imported cross-service (no
shared `cip_core` webhook helper exists yet); the header name and format
stay identical for platform consistency.
"""

from __future__ import annotations

import hashlib
import hmac

from cip_core import Unauthenticated

SIGNATURE_HEADER = "X-CIP-Signature"
_SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature CIP expects on webhook posts."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{mac}"


def verify_webhook_signature(*, secret: str, body: bytes, header_value: str | None) -> None:
    """Raise :class:`Unauthenticated` if the header doesn't match.

    Constant-time compare via :func:`hmac.compare_digest` so a bad
    signature can't be gleaned from timing.
    """
    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        raise Unauthenticated("Missing or malformed webhook signature")
    expected = compute_signature(secret, body)
    if not hmac.compare_digest(expected, header_value):
        raise Unauthenticated("Invalid webhook signature")
