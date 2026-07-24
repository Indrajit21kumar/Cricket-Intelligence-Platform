"""Ball Tracking API routes — M08 §10.

M08's production trigger is the ``video.normalized`` event; these sit alongside:

  POST /internal/ball/compute    sync compute for reprocessing / tests
  GET  /v1/ball/{correlationId}  the run summary for a clip

Tenant-scoped (RLS) via the ``X-Tenant-ID`` header bound by cip-core
middleware, with ``correlation_id`` — threaded from M05 — as the join key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ball_service.deps import Deps, get_deps
from ball_service.domain.ball_runs import get_ball_run
from ball_service.service import process_normalized
from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session

ball_router = APIRouter(prefix="/v1/ball", tags=["ball"])
internal_router = APIRouter(prefix="/internal/ball", tags=["internal"])


class ComputeRequest(BaseModel):
    """The M05 ``video.normalized`` payload, as a request body."""

    correlation_id: str = Field(..., min_length=1, max_length=64)
    normalized_ref: str = Field(..., min_length=1, description="Normalised-clip object ref")
    person_id: uuid.UUID | None = Field(None, description="The player the clip is of")
    fps: float | None = Field(None, gt=0, description="Frame rate, from M05")
    camera_angle: str | None = None
    pixel_to_meter: float | None = Field(None, gt=0)
    spatial_confidence: str | None = None
    quality_flags: list[dict[str, Any]] | None = None


class BallRunResponse(BaseModel):
    """Summary of one ball run. The track itself lives in the artefact."""

    correlation_id: str
    person_id: uuid.UUID | None
    model_version: str
    dataset_version: str | None
    frame_count: int
    frames_detected: int
    #: Overall confidence in this delivery's tracking, capped by capture conditions.
    track_confidence: float
    #: release_relative | absolute — M10 keys its timing model off this.
    timing_reference: str
    #: Did the capture-condition gate pass? Separates a bad clip from a good
    #: clip with no ball in shot.
    conditions_met: bool
    #: Absent events are absent KEYS, never zeroed frame numbers.
    events: dict[str, Any]
    #: ok | provisional | rejected
    quality: str
    artefact_ref: str | None
    created_at: datetime


def _to_response(row: dict[str, Any]) -> BallRunResponse:
    return BallRunResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        model_version=row["model_version"],
        dataset_version=row["dataset_version"],
        frame_count=row["frame_count"],
        frames_detected=row["frames_detected"],
        track_confidence=row["track_confidence"],
        timing_reference=row["timing_reference"],
        conditions_met=row["conditions_met"],
        events=row["events"],
        quality=row["quality"],
        artefact_ref=row["artefact_ref"],
        created_at=row["created_at"],
    )


@internal_router.post("/compute", response_model=BallRunResponse)
async def compute(
    body: ComputeRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BallRunResponse:
    """Track the ball on a clip; persists + publishes exactly as the consumer does."""
    tenant_id = require_tenant_id()
    row = await process_normalized(
        session_factory=deps.session_factory,
        tracker=deps.tracker,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        bat_client=deps.bat_client,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
        normalized_ref=body.normalized_ref,
        fps=body.fps,
        camera_angle=body.camera_angle,
        pixel_to_meter=body.pixel_to_meter,
        spatial_confidence=body.spatial_confidence,
        quality_flags=body.quality_flags,
    )
    return _to_response(row)


@ball_router.get("/{correlation_id}", response_model=BallRunResponse)
async def read_ball_run(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BallRunResponse:
    """Ball-run summary for a clip. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_ball_run(session, correlation_id)
    if row is None:
        raise NotFound("ball run not found")
    return _to_response(row)
