"""Billing API routes — M03.

- Step 2: GET /v1/plans (public catalogue)
- Step 3: POST /v1/entitlements/check (internal, cached)

Later steps add usage (4), subscriptions (5), webhooks/invoices (6),
and seats (8).
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
from cip_data import admin_session, tenant_session

plans_router = APIRouter(prefix="/v1/plans", tags=["plans"])
entitlements_router = APIRouter(prefix="/v1/entitlements", tags=["entitlements"])


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
