"""Billing API routes — M03.

- Step 2: GET /v1/plans (public catalogue)
- Step 3: POST /v1/entitlements/check (internal, cached)
- Step 4: POST /v1/usage (internal, idempotent metering)

Later steps add subscriptions (5), webhooks/invoices (6), and seats (8).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from billing_service.deps import Deps, get_deps
from billing_service.domain.entitlement_check import Resolved, check_entitlement
from billing_service.domain.plans import list_active_plans, resolve_entitlements
from billing_service.domain.subscriptions import get_active_subscription, tenant_from_subject
from billing_service.domain.usage import record_usage
from billing_service.domain.usage_counter import current_period
from cip_core import NotFound, require_idempotency_key
from cip_data import admin_session, tenant_session

plans_router = APIRouter(prefix="/v1/plans", tags=["plans"])
entitlements_router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])
usage_router = APIRouter(prefix="/v1/usage", tags=["usage"])


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
