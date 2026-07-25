"""Shot Recognition API routes — M09 §10.

M09's production trigger is the ``pose.keypoints`` event; these sit alongside:

  POST /internal/shot/classify    sync classify for reprocessing / tests
  GET  /v1/shot/{correlationId}   the run summary for a stroke

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header bound by cip-core
middleware, with ``correlation_id`` — threaded from M06 — as the join key.
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
from shot_service.deps import Deps, get_deps
from shot_service.domain.shot_runs import get_shot_run
from shot_service.service import process_stroke

shot_router = APIRouter(prefix="/v1/shot", tags=["shot"])
internal_router = APIRouter(prefix="/internal/shot", tags=["internal"])


class ClassifyRequest(BaseModel):
    """Sync classify entry. Inputs are fetched by correlation_id from the
    upstream signal sources, exactly as the consumer does."""

    correlation_id: str = Field(..., min_length=1, max_length=64)
    person_id: uuid.UUID | None = Field(None, description="The player the stroke is of")
    camera_angle: str | None = None


class ShotRunResponse(BaseModel):
    correlation_id: str
    person_id: uuid.UUID | None
    model_version: str
    dataset_version: str | None
    #: One of the v1 taxonomy, or 'unclassified' (abstention).
    shot_class: str
    shot_confidence: float
    #: Frame indices for stance/backlift/downswing/impact/follow_through.
    phase_boundaries: dict[str, int]
    #: standard (ball-anchored) | bat_only_fallback
    phase_method: str
    signals_used: list[str] | None
    #: ok | provisional | unclassified
    quality: str
    created_at: datetime


def _to_response(row: dict[str, Any]) -> ShotRunResponse:
    return ShotRunResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        model_version=row["model_version"],
        dataset_version=row["dataset_version"],
        shot_class=row["shot_class"],
        shot_confidence=row["shot_confidence"],
        phase_boundaries=row["phase_boundaries"],
        phase_method=row["phase_method"],
        signals_used=row["signals_used"],
        quality=row["quality"],
        created_at=row["created_at"],
    )


@internal_router.post("/classify", response_model=ShotRunResponse)
async def classify(
    body: ClassifyRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ShotRunResponse:
    """Classify a stroke; persists + publishes exactly as the consumer does."""
    tenant_id = require_tenant_id()
    row = await process_stroke(
        session_factory=deps.session_factory,
        classifier=deps.classifier,
        pose_source=deps.pose_source,
        bat_source=deps.bat_source,
        ball_source=deps.ball_source,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
        camera_angle=body.camera_angle,
    )
    if row is None:
        # No usable pose for this correlation — nothing to classify.
        raise Unprocessable("no pose available for this stroke")
    return _to_response(row)


@shot_router.get("/{correlation_id}", response_model=ShotRunResponse)
async def read_shot_run(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ShotRunResponse:
    """Shot-run summary for a stroke. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_shot_run(session, correlation_id)
    if row is None:
        raise NotFound("shot run not found")
    return _to_response(row)
