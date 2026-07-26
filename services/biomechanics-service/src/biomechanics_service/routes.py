"""Biomechanics API routes — M10 §13.

  POST /internal/v1/biomechanics/compute   sync compute (tests/reprocessing)
  GET  /v1/biomechanics/{strokeId}         report retrieval

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header; ``correlation_id`` (the
stroke id) is the key downstream joins on. The compute endpoint returns 200 for
a full report, 202 when the report is provisional (computed but degraded), and
422 when there is no assembleable fan-in to measure.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from biomechanics_service.deps import Deps, get_deps
from biomechanics_service.domain.reports_repo import get_report
from biomechanics_service.service import process_stroke
from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    Unprocessable,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session

biomechanics_router = APIRouter(prefix="/v1/biomechanics", tags=["biomechanics"])
internal_router = APIRouter(prefix="/internal/v1/biomechanics", tags=["internal"])


class ComputeRequest(BaseModel):
    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID | None = None


class ReportResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    shot_type: str | None
    shot_confidence: float | None
    phase_boundaries: dict[str, int]
    phase_method: str | None
    metrics: dict[str, Any]
    quality: dict[str, Any]
    schema_version: str
    out_of_expected_range: bool
    provisional: bool
    computed_at: datetime


def _to_response(row: dict[str, Any]) -> ReportResponse:
    return ReportResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        shot_type=row["shot_type"],
        shot_confidence=row["shot_confidence"],
        phase_boundaries=row["phase_boundaries"],
        phase_method=row["phase_method"],
        metrics=row["metrics"],
        quality=row["quality"],
        schema_version=row["schema_version"],
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
    """Compute a report; 202 when provisional, 422 when nothing to measure."""
    tenant_id = require_tenant_id()
    row = await process_stroke(
        session_factory=deps.session_factory,
        stroke_source=deps.stroke_source,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
    )
    if row is None:
        raise Unprocessable("no assembleable inputs for this stroke")
    if row["provisional"]:
        response.status_code = status.HTTP_202_ACCEPTED
    return _to_response(row)


@biomechanics_router.get("/{correlation_id}", response_model=ReportResponse)
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
        raise NotFound("biomechanics report not found")
    return _to_response(row)
