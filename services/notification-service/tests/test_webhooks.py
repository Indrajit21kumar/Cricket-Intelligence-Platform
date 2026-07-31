"""Provider webhook signature verification (M19 Step 6)."""

from __future__ import annotations

import pytest

from cip_core import Unauthenticated
from notification_service.domain.webhooks import compute_signature, verify_webhook_signature

_SECRET = "test-secret"
_BODY = b'{"provider_ref": "abc", "delivered": true}'


class TestVerifyWebhookSignature:
    def test_a_correctly_signed_body_verifies(self) -> None:
        header = compute_signature(_SECRET, _BODY)
        verify_webhook_signature(secret=_SECRET, body=_BODY, header_value=header)

    def test_missing_header_raises(self) -> None:
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=_SECRET, body=_BODY, header_value=None)

    def test_malformed_header_without_prefix_raises(self) -> None:
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=_SECRET, body=_BODY, header_value="not-a-signature")

    def test_wrong_secret_raises(self) -> None:
        header = compute_signature("a-different-secret", _BODY)
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=_SECRET, body=_BODY, header_value=header)

    def test_tampered_body_raises(self) -> None:
        header = compute_signature(_SECRET, _BODY)
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=_SECRET, body=_BODY + b"tampered", header_value=header)
