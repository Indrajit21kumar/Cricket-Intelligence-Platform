"""Learning API routes — M17 §10.

  GET  /v1/players/{person_id}/plan   current training plan (auth + consent scoped)
  POST /internal/v1/learning/plan     sync plan build (tests/reprocessing)

Tenant-scoped (RLS) via the caller's tenant context.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    Unprocessable,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session
from learning_service.deps import Deps, get_deps
from learning_service.domain import plans_repo
from learning_service.service import build_plan

players_router = APIRouter(prefix="/v1/players", tags=["players"])
internal_router = APIRouter(prefix="/internal/v1/learning", tags=["internal"])


class PlanRequest(BaseModel):
    person_id: uuid.UUID
    session_ref: str = Field(..., min_length=1, max_length=64)


class PlanResponse(BaseModel):
    person_id: uuid.UUID | None
    session_ref: str
    stage: str
    items: list[dict[str, Any]]
    targets: list[str]
    active: bool
    schema_version: str
    created_at: datetime


def _to_response(row: dict[str, Any]) -> PlanResponse:
    return PlanResponse(
        person_id=row["person_id"],
        session_ref=row["session_ref"],
        stage=row["stage"],
        items=row["items"],
        targets=row["targets"],
        active=row["active"],
        schema_version=row["schema_version"],
        created_at=row["created_at"],
    )


@internal_router.post("/plan", response_model=PlanResponse)
async def run_build_plan(
    body: PlanRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> PlanResponse:
    """Build a plan synchronously; 422 when the tenant can't be resolved."""
    row = await build_plan(
        session_factory=deps.session_factory,
        findings_source=deps.findings_source,
        benchmark_source=deps.benchmark_source,
        dna_history_source=deps.dna_history_source,
        deviation_source=deps.deviation_source,
        tenant_resolver=deps.tenant_resolver,
        event_bus=deps.event_bus,
        person_id=body.person_id,
        session_ref=body.session_ref,
    )
    if row is None:
        raise Unprocessable("could not resolve a tenant, or this cycle was already processed")
    return _to_response(row)


@players_router.get("/{person_id}/plan", response_model=PlanResponse)
async def read_active_plan(
    person_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> PlanResponse:
    """The player's current active plan. RLS scopes the lookup to the caller's tenant."""
    tenant_id = require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await plans_repo.get_active_plan(session, tenant_id=tenant_id, person_id=person_id)
    if row is None:
        raise NotFound("no active training plan for this player")
    return _to_response(row)
