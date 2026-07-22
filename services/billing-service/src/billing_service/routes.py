"""Billing API routes — M03.

- Step 2: GET /v1/plans (public catalogue)
- Step 3: POST /v1/entitlements/check (internal, cached)
- Step 4: POST /v1/usage (internal, idempotent metering)
- Step 5: POST/PATCH/GET /v1/subscriptions (lifecycle + proration)
- Step 6: POST /v1/webhooks/payments (signed) + GET /v1/invoices

Later step adds seats (8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field

from billing_service.deps import Deps, get_deps
from billing_service.domain.dunning import (
    NOTIFICATION_TOPIC,
    DunningState,
    process_failed_charge,
    process_successful_charge,
)
from billing_service.domain.entitlement_check import Resolved, check_entitlement, invalidate_keys
from billing_service.domain.invoices import list_invoices_for_tenant, record_invoice
from billing_service.domain.payments import SIGNATURE_HEADER, verify_webhook_signature
from billing_service.domain.plans import (
    get_plan,
    get_plan_by_code,
    list_active_plans,
    resolve_entitlements,
)
from billing_service.domain.proration import compute_proration
from billing_service.domain.subscriptions import (
    cancel_subscription,
    change_plan,
    create_subscription,
    get_active_subscription,
    get_subscription,
    tenant_from_subject,
)
from billing_service.domain.usage import record_usage
from billing_service.domain.usage_counter import current_period
from cip_core import BadRequest, Conflict, NotFound, require_idempotency_key, require_role, roles
from cip_core.auth import AuthenticatedPrincipal
from cip_data import admin_session, tenant_session
from cip_events import EventEnvelope

plans_router = APIRouter(prefix="/v1/plans", tags=["plans"])
entitlements_router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])
usage_router = APIRouter(prefix="/v1/usage", tags=["usage"])
subscriptions_router = APIRouter(prefix="/v1/subscriptions", tags=["subscriptions"])
webhooks_router = APIRouter(prefix="/v1/webhooks", tags=["webhooks"])
invoices_router = APIRouter(prefix="/v1/invoices", tags=["invoices"])


class PlanView(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    version: int
    price_minor: int = Field(..., description="Price in minor units (paise)")
    currency: str
    entitlements: dict[str, str]


@plans_router.get("", response_model=list[PlanView])
async def list_plans(deps: Annotated[Deps, Depends(get_deps)]) -> list[PlanView]:
    """List active plans + their entitlements (public catalogue)."""
    async with admin_session(deps.session_factory) as session:
        plans = await list_active_plans(session)
    return [PlanView(**p) for p in plans]


class EntitlementCheckRequest(BaseModel):
    subject: str = Field(..., description="'tenant:<uuid>' — the billing subject")
    key: str = Field(..., description="Entitlement key, e.g. 'feature.ai_coach'")


class EntitlementCheckResponse(BaseModel):
    allowed: bool
    remaining: int | None = Field(None, description="None for flags; -1 = unlimited")
    cached: bool
    degraded: bool = Field(False, description="Served from last-known-good on outage")


@entitlements_router.post("/check", response_model=EntitlementCheckResponse)
async def check(
    body: EntitlementCheckRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> EntitlementCheckResponse:
    """Internal entitlement check for feature modules. Cached; <30ms warm."""
    tenant_id = tenant_from_subject(body.subject)

    async def _resolver(tid: uuid.UUID) -> Resolved | None:
        async with tenant_session(deps.session_factory, tenant_id=tid) as session:
            sub = await get_active_subscription(session, tid)
            if sub is None:
                return None
            ents = await resolve_entitlements(session, sub["plan_id"])
            return {"subscription_id": str(sub["id"]), "entitlements": ents}

    result = await check_entitlement(
        deps.redis, tenant_id=tenant_id, key=body.key, resolver=_resolver
    )
    return EntitlementCheckResponse(
        allowed=result.allowed,
        remaining=result.remaining,
        cached=result.cached,
        degraded=result.degraded,
    )


class UsageRequest(BaseModel):
    subject: str = Field(..., description="'tenant:<uuid>' — the billing subject")
    meter_key: str = Field("analysis.consumed", description="Metered unit")
    qty: int = Field(1, ge=1)


class UsageResponse(BaseModel):
    recorded: bool = Field(..., description="False if this was a duplicate (no-op)")
    total: int = Field(..., description="Usage total for the current period")
    period: str


@usage_router.post("", response_model=UsageResponse)
async def record_usage_endpoint(
    body: UsageRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> UsageResponse:
    """Record a metered usage event exactly-once (Idempotency-Key required)."""
    tenant_id = tenant_from_subject(body.subject)
    period = current_period()

    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        sub = await get_active_subscription(session, tenant_id)
        if sub is None:
            raise NotFound("No active subscription for that subject")
        result = await record_usage(
            session,
            deps.redis,
            tenant_id=tenant_id,
            subscription_id=sub["id"],
            meter_key=body.meter_key,
            qty=body.qty,
            idempotency_key=idempotency_key,
            period=period,
        )

    return UsageResponse(recorded=result.recorded, total=result.total, period=period)


# --- Subscription lifecycle (M03 Step 5, AC-M03-01, FR-M03-02/06) -----------
#
# RBAC-gated (§11): only tenant admins can subscribe/change/cancel for their
# own tenant. platform_admin can act on any tenant (support/ops).


_TENANT_ADMIN_ROLES = (roles.ACADEMY_ADMIN, roles.ORG_ADMIN, roles.PLATFORM_ADMIN)


class SubscribeRequest(BaseModel):
    subject: str = Field(..., description="'tenant:<uuid>' — the billing subject")
    plan_code: str = Field(..., description="Plan code, e.g. 'starter', 'pro'")
    trialing: bool = Field(False, description="Start on a free trial period")


class SubscriptionView(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    subject_ref: str
    plan_id: uuid.UUID
    plan_code: str
    status: str
    period_start: datetime
    period_end: datetime


class ProrationView(BaseModel):
    fraction_remaining: float
    credit_minor: int
    charge_minor: int
    net_minor: int


class SubscriptionChangeResponse(BaseModel):
    subscription: SubscriptionView
    proration: ProrationView | None = Field(
        None, description="Populated on plan change; null for cancel"
    )


def _to_view(sub: dict[str, Any], plan_code: str) -> SubscriptionView:
    return SubscriptionView(
        id=sub["id"],
        tenant_id=sub["tenant_id"],
        subject_ref=str(sub["subject_ref"]),
        plan_id=sub["plan_id"],
        plan_code=plan_code,
        status=str(sub["status"]),
        period_start=sub["period_start"],
        period_end=sub["period_end"],
    )


@subscriptions_router.post("", response_model=SubscriptionView, status_code=201)
async def subscribe(
    body: SubscribeRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*_TENANT_ADMIN_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> SubscriptionView:
    """Create a subscription for a tenant (AC-M03-01: subscribe)."""
    _ = principal  # RBAC gate; audit lands with Step 8's audit helper.
    tenant_id = tenant_from_subject(body.subject)

    async with admin_session(deps.session_factory) as session:
        plan = await get_plan_by_code(session, body.plan_code)
    if plan is None:
        raise NotFound(f"Plan '{body.plan_code}' not found")

    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        existing = await get_active_subscription(session, tenant_id)
        if existing is not None:
            raise Conflict("Tenant already has an active subscription; PATCH it to change plan")
        sub = await create_subscription(
            session,
            tenant_id=tenant_id,
            subject_ref=body.subject,
            plan_id=plan["id"],
            trialing=body.trialing,
        )

    # New subscription -> future entitlement checks must re-resolve.
    for k in invalidate_keys(tenant_id):
        await deps.redis.delete(k)

    return _to_view(sub, plan["code"])


class ChangeSubscriptionRequest(BaseModel):
    """PATCH body: exactly one of ``plan_code`` (upgrade/downgrade) or
    ``action='cancel'``. ``subject`` names the tenant scope (RLS)."""

    subject: str = Field(..., description="'tenant:<uuid>' — the billing subject")
    plan_code: str | None = Field(None, description="New plan code for upgrade/downgrade")
    action: str | None = Field(None, description="'cancel' to terminate the subscription")


@subscriptions_router.get("/{subscription_id}", response_model=SubscriptionView)
async def get_one(
    subscription_id: uuid.UUID,
    subject: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*_TENANT_ADMIN_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> SubscriptionView:
    """Fetch a subscription (RLS: caller supplies ``?subject=tenant:<uuid>``)."""
    _ = principal
    tenant_id = tenant_from_subject(subject)
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        sub = await get_subscription(session, subscription_id)
    if sub is None:
        # Either wrong subscription id, or subject doesn't own it. Return the
        # same 404 either way so it can't be used to enumerate other tenants'
        # subscriptions.
        raise NotFound("Subscription not found")
    async with admin_session(deps.session_factory) as session:
        plan = await get_plan(session, sub["plan_id"])
    assert plan is not None  # FK guarantees this
    return _to_view(sub, plan["code"])


@subscriptions_router.patch("/{subscription_id}", response_model=SubscriptionChangeResponse)
async def change_subscription(
    subscription_id: uuid.UUID,
    body: ChangeSubscriptionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*_TENANT_ADMIN_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> SubscriptionChangeResponse:
    """Upgrade/downgrade (prorated) or cancel a subscription (AC-M03-01)."""
    _ = principal

    if bool(body.plan_code) == bool(body.action):
        raise BadRequest(
            "Provide exactly one of 'plan_code' (upgrade/downgrade) or 'action=cancel'"
        )
    if body.action is not None and body.action != "cancel":
        raise BadRequest("Unsupported action; only 'cancel' is accepted")

    tenant_id = tenant_from_subject(body.subject)

    # Read the subscription under its own tenant scope (RLS) so subject/id
    # must agree — cross-tenant attempts get an honest 404.
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        sub = await get_subscription(session, subscription_id)
    if sub is None:
        raise NotFound("Subscription not found")

    # Plans are global (no RLS) — look them up under admin.
    async with admin_session(deps.session_factory) as session:
        old_plan = await get_plan(session, sub["plan_id"])
        new_plan = None
        if body.plan_code is not None:
            new_plan = await get_plan_by_code(session, body.plan_code)
            if new_plan is None:
                raise NotFound(f"Plan '{body.plan_code}' not found")
    assert old_plan is not None

    proration: ProrationView | None = None

    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        if body.action == "cancel":
            updated = await cancel_subscription(session, subscription_id=subscription_id)
            resolved_plan = old_plan
        else:
            assert new_plan is not None
            if new_plan["id"] == old_plan["id"]:
                raise BadRequest("Subscription is already on that plan")
            p = compute_proration(
                old_price_minor=int(old_plan["price_minor"]),
                new_price_minor=int(new_plan["price_minor"]),
                period_start=sub["period_start"],
                period_end=sub["period_end"],
                at=datetime.now(UTC),
            )
            proration = ProrationView(
                fraction_remaining=p.fraction_remaining,
                credit_minor=p.credit_minor,
                charge_minor=p.charge_minor,
                net_minor=p.net_minor,
            )
            updated = await change_plan(
                session, subscription_id=subscription_id, new_plan_id=new_plan["id"]
            )
            resolved_plan = new_plan

    # Plan / status change -> drop the fresh entitlement cache so the next
    # check re-resolves. (LKG survives so an outage stays gracefully served.)
    for k in invalidate_keys(tenant_id):
        await deps.redis.delete(k)

    return SubscriptionChangeResponse(
        subscription=_to_view(updated, resolved_plan["code"]),
        proration=proration,
    )


# --- Webhooks + invoices (M03 Step 6, AC-M03-04, FR-M03-05, NFR-M03-04) -----
#
# CIP does not move money — the provider does. This route:
#   1. verifies the provider's HMAC signature on the raw body (§11)
#   2. looks up which of *our* subscriptions this event refers to
#   3. writes an immutable invoice row keyed on ``provider_ref``
#   4. publishes an ``invoice.paid`` event for M20 on a paid charge (FR-M03-09)
#
# The invoice write is idempotent on ``provider_ref`` — a redelivered webhook
# is silently a no-op, which is the replay-safety half of AC-M03-04.


class WebhookPayload(BaseModel):
    """The event shape our fake provider emits; a real Stripe/Razorpay
    adapter would translate their payload to this shape before recording.
    """

    event_id: str = Field(..., min_length=1)
    event_type: str = Field(..., description="charge.succeeded | charge.failed")
    provider_ref: str = Field(..., min_length=1, description="Provider charge id")
    subscription_id: uuid.UUID
    tenant_id: uuid.UUID
    amount_minor: int = Field(..., ge=0)
    currency: str = Field("INR", min_length=3, max_length=3)
    occurred_at: datetime


class WebhookAck(BaseModel):
    recorded: bool = Field(..., description="False if this event was a replay")
    invoice_id: uuid.UUID
    status: str


_EVENT_TO_INVOICE_STATUS = {
    "charge.succeeded": "paid",
    "charge.failed": "failed",
}


@webhooks_router.post("/payments", response_model=WebhookAck)
async def payment_webhook(
    request: Request,
    deps: Annotated[Deps, Depends(get_deps)],
    x_signature: Annotated[str | None, Header(alias=SIGNATURE_HEADER)] = None,
) -> WebhookAck:
    """Receive a signed payment-provider webhook. Records the invoice.

    Auth is the signature — no bearer token. That mirrors how every real
    provider posts: they don't have a CIP JWT, they have a shared secret.
    """
    body = await request.body()

    # Reject BEFORE parsing so replay/tamper isn't given a free schema
    # validation error message that would leak info about the payload.
    verify_webhook_signature(
        secret=deps.settings.payment_webhook_secret, body=body, header_value=x_signature
    )

    payload = WebhookPayload.model_validate_json(body)

    if payload.event_type not in _EVENT_TO_INVOICE_STATUS:
        raise BadRequest(f"Unsupported event_type '{payload.event_type}'")
    invoice_status = _EVENT_TO_INVOICE_STATUS[payload.event_type]

    dunning_state: DunningState | None = None
    async with tenant_session(deps.session_factory, tenant_id=payload.tenant_id) as session:
        # A well-behaved provider will only send events for known subs, but
        # we still verify — a leaked webhook secret plus a fake subscription
        # id should not create phantom invoices.
        sub = await get_subscription(session, payload.subscription_id)
        if sub is None:
            raise NotFound("Subscription not found for webhook event")

        row, inserted = await record_invoice(
            session,
            tenant_id=payload.tenant_id,
            subscription_id=payload.subscription_id,
            amount_minor=payload.amount_minor,
            currency=payload.currency,
            status=invoice_status,
            provider_ref=payload.provider_ref,
            issued_at=payload.occurred_at,
        )

        # Advance the dunning state machine, but only on a NEW invoice —
        # a replayed webhook must not push a subscription through the state
        # machine twice (that would suspend prematurely on the 4th replay).
        if inserted:
            if invoice_status == "failed":
                dunning_state = await process_failed_charge(
                    session, subscription_id=payload.subscription_id
                )
            elif invoice_status == "paid":
                dunning_state = await process_successful_charge(
                    session, subscription_id=payload.subscription_id
                )

    # Publish invoice.paid only on new + successful writes. Replays and
    # failures don't emit — the event stream stays a truthful ledger for M20.
    if inserted and invoice_status == "paid":
        envelope = EventEnvelope(
            correlation_id=payload.event_id,
            tenant_id=payload.tenant_id,
            schema_version="1.0.0",
            idempotency_key=f"invoice.paid:{payload.provider_ref}",
            payload={
                "invoice_id": str(row["id"]),
                "subscription_id": str(payload.subscription_id),
                "amount_minor": payload.amount_minor,
                "currency": payload.currency,
                "issued_at": payload.occurred_at.astimezone(UTC).isoformat(),
            },
        )
        await deps.event_bus.publish("billing.invoice.paid", envelope)

    # Dunning state change -> notify M19 + drop the entitlement cache so a
    # newly-suspended subscription can't sneak through the fast path.
    if dunning_state is not None:
        notify = EventEnvelope(
            correlation_id=payload.event_id,
            tenant_id=payload.tenant_id,
            schema_version="1.0.0",
            idempotency_key=(
                f"{dunning_state.template}:{payload.subscription_id}:{payload.provider_ref}"
            ),
            payload={
                "subscription_id": str(payload.subscription_id),
                "invoice_id": str(row["id"]),
                "template": dunning_state.template,
                "attempt_number": dunning_state.attempt_number,
                "next_retry_at": (
                    dunning_state.next_retry_at.isoformat()
                    if dunning_state.next_retry_at is not None
                    else None
                ),
                "action": dunning_state.action,
            },
        )
        await deps.event_bus.publish(NOTIFICATION_TOPIC, notify)

        # Any status transition (past_due / suspended / recovered) means the
        # cached entitlement snapshot is stale. LKG survives so entitlement
        # checks still degrade gracefully if the DB is unreachable.
        for k in invalidate_keys(payload.tenant_id):
            await deps.redis.delete(k)

    return WebhookAck(recorded=inserted, invoice_id=row["id"], status=row["status"])


# --- Invoices ---------------------------------------------------------------


class InvoiceView(BaseModel):
    id: uuid.UUID
    subscription_id: uuid.UUID
    amount_minor: int
    currency: str
    status: str
    provider_ref: str
    issued_at: datetime


@invoices_router.get("", response_model=list[InvoiceView])
async def list_invoices(
    subject: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(*_TENANT_ADMIN_ROLES))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[InvoiceView]:
    """List invoices for the subject's tenant (RLS-scoped)."""
    _ = principal
    tenant_id = tenant_from_subject(subject)
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        rows = await list_invoices_for_tenant(session, tenant_id)
    return [
        InvoiceView(
            id=r["id"],
            subscription_id=r["subscription_id"],
            amount_minor=r["amount_minor"],
            currency=r["currency"],
            status=r["status"],
            provider_ref=r["provider_ref"],
            issued_at=r["issued_at"],
        )
        for r in rows
    ]
