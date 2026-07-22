"""Billing API routes — M03.

Step 2 ships the public plan catalogue. Later steps add entitlements/check
(3), usage (4), subscriptions (5), webhooks/invoices (6), and seats (8).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from billing_service.deps import Deps, get_deps
from billing_service.domain.plans import list_active_plans
from cip_data import admin_session

plans_router = APIRouter(prefix="/v1/plans", tags=["plans"])


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
