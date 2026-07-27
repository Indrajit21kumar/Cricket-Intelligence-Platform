"""Physics API routes — M11 §12.

  POST /internal/v1/physics/compute   sync compute (tests/reprocessing)
  GET  /v1/physics/{strokeId}         report retrieval (auth + consent scoped)

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header; ``correlation_id`` (the
stroke id) is the key downstream joins on. The compute endpoint returns 200 for
a full report, 202 when the report is provisional (computed but degraded), and
422 when there is no assembleable biomechanics to turn into physics.
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
from physics_service.deps import Deps, get_deps
from physics_service.domain.reports_repo import get_report
from physics_service.service import process_stroke

physics_router = APIRouter(prefix="/v1/physics", tags=["physics"])
internal_router = APIRouter(prefix="/internal/v1/physics", tags=["internal"])


class ComputeRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID | None = None


class ReportResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    shot_type: str | None
    shot_confidence: float | None
    quantities: dict[str, Any]
    kinetic_chain: dict[str, Any]
    quality: dict[str, Any]
    schema_version: str
    model_version: str
    out_of_expected_range: bool
    provisional: bool
    computed_at: datetime


def _to_response(row: dict[str, Any]) -> ReportResponse:
    return ReportResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        shot_type=row["shot_type"],
        shot_confidence=row["shot_confidence"],
        quantities=row["quantities"],
        kinetic_chain=row["kinetic_chain"],
        quality=row["quality"],
        schema_version=row["schema_version"],
        model_version=row["model_version"],
        out_of_expected_range=row["out_of_expected_range"],
        provisional=row["provisional"],
        computed_at=row["computed_at"],
    )


@internal_router.post("/compute", response_model=ReportResponse)
async def compute(
    body: ComputeRequest,
    response: Response,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ReportResponse:
    """Compute a report; 202 when provisional, 422 when nothing to compute."""
    tenant_id = require_tenant_id()
    row = await process_stroke(
        session_factory=deps.session_factory,
        source=deps.source,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
    )
    if row is None:
        raise Unprocessable("no assembleable biomechanics for this stroke")
    if row["provisional"]:
        response.status_code = status.HTTP_202_ACCEPTED
    return _to_response(row)


@physics_router.get("/{correlation_id}", response_model=ReportResponse)
async def read_report(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ReportResponse:
    """Report retrieval. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_report(session, correlation_id)
    if row is None:
        raise NotFound("physics report not found")
    return _to_response(row)
