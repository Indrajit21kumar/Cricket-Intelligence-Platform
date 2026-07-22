"""Payment-provider adapter + fake provider + webhook signature verification
(M03 Step 6, FR-M03-05, NFR-M03-03, AC-M03-04).

Design (§8 boundary rule): CIP never moves money. The external provider
tokenises the card, holds funds, and settles. CIP records intent and
reconciles against the provider's authoritative record via webhooks.

The :class:`PaymentProvider` protocol lets us plug in Stripe / Razorpay
later without touching billing service code — Step 6 ships a
:class:`FakePaymentProvider` (deterministic, in-process) so tests and dev
run without any real payment account or money in flight. Wire the real
provider by binding ``deps.payment_provider`` to the concrete class in
``build_deps``; the routes are provider-agnostic.

**No raw card data enters the process**: :meth:`create_charge` takes an
amount + a customer reference. Card details, if any, are collected on the
provider's own hosted page and never round-trip through CIP (NFR-M03-03).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from cip_core import Unauthenticated

# --- Provider adapter --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Charge:
    """Result of a create_charge call — reference the provider will emit on webhooks."""

    provider_ref: str  # e.g. Stripe charge id 'ch_xxx' or fake 'fake_xxx'
    status: str  # "pending" | "succeeded" | "failed"


class PaymentProvider(Protocol):
    """Adapter contract every payment provider (Stripe, Razorpay, fake) satisfies."""

    async def create_customer(self, *, subject_ref: str, email: str | None = None) -> str:
        """Register a customer with the provider, returning the provider id."""
        ...

    async def create_charge(
        self,
        *,
        customer_ref: str,
        amount_minor: int,
        currency: str,
        description: str,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> Charge:
        """Create a charge; returns a provider ref + initial status.

        Idempotency-key on the provider side means retries are safe.
        """
        ...


# --- Fake provider (dev + tests) --------------------------------------------


class FakePaymentProvider:
    """In-process provider used for dev + tests.

    Deterministic + observable: every created charge is remembered in
    :attr:`charges` so tests can drive webhook payloads against known refs.
    ``fail_next`` lets a test flip the next :meth:`create_charge` to a
    failed status without touching internal state — this is the seam
    Step 7's dunning tests hang off.
    """

    def __init__(self) -> None:
        self.charges: dict[str, dict[str, Any]] = {}
        self.customers: dict[str, str] = {}  # subject_ref -> provider customer id
        self.fail_next: bool = False

    async def create_customer(self, *, subject_ref: str, email: str | None = None) -> str:
        _ = email  # accepted for API compatibility with real providers
        if subject_ref in self.customers:
            return self.customers[subject_ref]
        cust_ref = f"fake_cus_{uuid.uuid4().hex[:12]}"
        self.customers[subject_ref] = cust_ref
        return cust_ref

    async def create_charge(
        self,
        *,
        customer_ref: str,
        amount_minor: int,
        currency: str,
        description: str,
        idempotency_key: str,
        metadata: dict[str, str] | None = None,
    ) -> Charge:
        # Idempotency: a repeat with the same key returns the earlier charge.
        for charge in self.charges.values():
            if charge["idempotency_key"] == idempotency_key:
                return Charge(provider_ref=charge["provider_ref"], status=charge["status"])

        status = "failed" if self.fail_next else "succeeded"
        self.fail_next = False
        provider_ref = f"fake_ch_{uuid.uuid4().hex[:12]}"
        self.charges[provider_ref] = {
            "provider_ref": provider_ref,
            "customer_ref": customer_ref,
            "amount_minor": amount_minor,
            "currency": currency,
            "description": description,
            "idempotency_key": idempotency_key,
            "status": status,
            "metadata": metadata or {},
            "created_at": datetime.now(UTC),
        }
        return Charge(provider_ref=provider_ref, status=status)


# --- Webhook signature verification -----------------------------------------
#
# Standard HMAC-SHA256 over the raw request body. The header format matches
# what most providers use so a real integration is a drop-in:
#     X-CIP-Signature: sha256=<hex>
# We verify against the *raw* body — parsing to JSON first would let a
# reformatting proxy silently invalidate signatures.


SIGNATURE_HEADER = "X-CIP-Signature"
_SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, body: bytes) -> str:
    """Return the ``sha256=<hex>`` signature CIP expects on webhook posts."""
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"{_SIGNATURE_PREFIX}{mac}"


def verify_webhook_signature(*, secret: str, body: bytes, header_value: str | None) -> None:
    """Raise :class:`Unauthenticated` if the header doesn't match.

    Constant-time compare via :func:`hmac.compare_digest` so a bad signature
    can't be gleaned from timing.
    """
    if not header_value or not header_value.startswith(_SIGNATURE_PREFIX):
        raise Unauthenticated("Missing or malformed webhook signature")
    expected = compute_signature(secret, body)
    if not hmac.compare_digest(expected, header_value):
        raise Unauthenticated("Invalid webhook signature")
