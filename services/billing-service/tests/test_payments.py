"""Unit tests for the payment adapter + webhook signature verification
(M03 Step 6, FR-M03-05, NFR-M03-03).

Pure code, no DB / no Redis / no HTTP — the fake provider and the HMAC
verify are trivially testable in isolation.
"""

from __future__ import annotations

import pytest

from billing_service.domain.payments import (
    FakePaymentProvider,
    compute_signature,
    verify_webhook_signature,
)
from cip_core import Unauthenticated

SECRET = "test-webhook-secret"


class TestFakeProvider:
    async def test_create_customer_is_idempotent(self) -> None:
        p = FakePaymentProvider()
        first = await p.create_customer(subject_ref="tenant:abc")
        second = await p.create_customer(subject_ref="tenant:abc")
        assert first == second

    async def test_create_charge_default_success(self) -> None:
        p = FakePaymentProvider()
        cust = await p.create_customer(subject_ref="tenant:x")
        ch = await p.create_charge(
            customer_ref=cust,
            amount_minor=49_900,
            currency="INR",
            description="pro subscription",
            idempotency_key="k1",
        )
        assert ch.status == "succeeded"
        assert ch.provider_ref.startswith("fake_ch_")

    async def test_create_charge_fail_next_flips_once(self) -> None:
        """``fail_next`` is one-shot — the flag clears after being used."""
        p = FakePaymentProvider()
        cust = await p.create_customer(subject_ref="tenant:x")
        p.fail_next = True
        first = await p.create_charge(
            customer_ref=cust,
            amount_minor=1,
            currency="INR",
            description="x",
            idempotency_key="k1",
        )
        assert first.status == "failed"

        second = await p.create_charge(
            customer_ref=cust,
            amount_minor=1,
            currency="INR",
            description="x",
            idempotency_key="k2",
        )
        assert second.status == "succeeded"

    async def test_charge_idempotency_key_reuses_charge(self) -> None:
        p = FakePaymentProvider()
        cust = await p.create_customer(subject_ref="tenant:x")
        a = await p.create_charge(
            customer_ref=cust,
            amount_minor=1,
            currency="INR",
            description="x",
            idempotency_key="same-key",
        )
        b = await p.create_charge(
            customer_ref=cust,
            amount_minor=1,
            currency="INR",
            description="x",
            idempotency_key="same-key",
        )
        assert a.provider_ref == b.provider_ref  # No new charge on retry.


class TestSignatureVerification:
    def test_valid_signature_accepts(self) -> None:
        body = b'{"event_id":"e1"}'
        sig = compute_signature(SECRET, body)
        # No exception -> pass.
        verify_webhook_signature(secret=SECRET, body=body, header_value=sig)

    def test_missing_header_rejected(self) -> None:
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=SECRET, body=b"", header_value=None)

    def test_wrong_prefix_rejected(self) -> None:
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=SECRET, body=b"", header_value="md5=deadbeef")

    def test_tampered_body_rejected(self) -> None:
        original = b'{"amount_minor": 100}'
        tampered = b'{"amount_minor": 100000}'
        sig = compute_signature(SECRET, original)
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=SECRET, body=tampered, header_value=sig)

    def test_wrong_secret_rejected(self) -> None:
        body = b"payload"
        sig_with_wrong_secret = compute_signature("attacker-guess", body)
        with pytest.raises(Unauthenticated):
            verify_webhook_signature(secret=SECRET, body=body, header_value=sig_with_wrong_secret)
