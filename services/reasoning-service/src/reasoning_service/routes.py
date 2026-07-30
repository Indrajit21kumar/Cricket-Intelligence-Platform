"""Reasoning API routes — M13 §11.

  POST /internal/v1/reasoning/run   sync run (tests/reprocessing)
  GET  /v1/reasoning/{strokeId}     result retrieval (auth + consent scoped)

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header; ``correlation_id`` (the
stroke id) is the key downstream joins on. The run endpoint returns 200 for a
full result, 202 when the result is provisional (computed but degraded), and
422 when there are no assembleable facts to reason about.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    Unprocessable,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session
from reasoning_service.deps import Deps, get_deps
from reasoning_service.domain.reports_repo import get_result
from reasoning_service.service import process_stroke

reasoning_router = APIRouter(prefix="/v1/reasoning", tags=["reasoning"])
internal_router = APIRouter(prefix="/internal/v1/reasoning", tags=["internal"])


class RunRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID | None = None


class ResultResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    shot_type: str | None
    shot_confidence: float | None
    kg_version: str
    findings: list[dict[str, Any]]
    match_risk: dict[str, Any]
    quality: dict[str, Any]
    schema_version: str
    provisional: bool
    computed_at: datetime


def _to_response(row: dict[str, Any]) -> ResultResponse:
    return ResultResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        shot_type=row["shot_type"],
        shot_confidence=row["shot_confidence"],
        kg_version=row["kg_version"],
        findings=row["findings"],
        match_risk=row["match_risk"],
        quality=row["quality"],
        schema_version=row["schema_version"],
        provisional=row["provisional"],
        computed_at=row["computed_at"],
    )


@internal_router.post("/run", response_model=ResultResponse)
async def run_reasoning(
    body: RunRequest,
    response: Response,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ResultResponse:
    """Run reasoning; 202 when provisional, 422 when nothing to reason about."""
    tenant_id = require_tenant_id()
    row = await process_stroke(
        session_factory=deps.session_factory,
        fact_source=deps.fact_source,
        knowledge_source=deps.knowledge_source,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
    )
    if row is None:
        raise Unprocessable("no assembleable facts for this stroke")
    if row["provisional"]:
        response.status_code = status.HTTP_202_ACCEPTED
    return _to_response(row)


@reasoning_router.get("/{correlation_id}", response_model=ResultResponse)
async def read_result(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ResultResponse:
    """Retrieve a reasoning result. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_result(session, correlation_id)
    if row is None:
        raise NotFound("reasoning result not found")
    return _to_response(row)
