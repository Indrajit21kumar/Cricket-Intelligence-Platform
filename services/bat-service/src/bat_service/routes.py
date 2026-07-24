"""Bat Detection API routes — M07 §10.

M07's production trigger is the ``video.normalized`` event, not a request;
these endpoints sit alongside it:

  POST /internal/bat/compute   sync compute for reprocessing / tests
  GET  /v1/bat/{correlationId} the run summary for a clip

Tenant-scoped (RLS): the tenant comes from the ``X-Tenant-ID`` header bound by
cip-core middleware, and ``correlation_id`` — threaded from M05 — is the key
everything downstream joins on.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bat_service.deps import Deps, get_deps
from bat_service.domain.bat_runs import get_bat_run
from bat_service.service import process_normalized
from cip_core import (
    AuthenticatedPrincipal,
    NotFound,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session

bat_router = APIRouter(prefix="/v1/bat", tags=["bat"])
internal_router = APIRouter(prefix="/internal/bat", tags=["internal"])


class ComputeRequest(BaseModel):
    """The M05 ``video.normalized`` payload, as a request body."""

    correlation_id: str = Field(..., min_length=1, max_length=64)
    normalized_ref: str = Field(..., min_length=1, description="Normalised-clip object ref")
    person_id: uuid.UUID | None = Field(None, description="The player the clip is of")
    camera_angle: str | None = None
    spatial_confidence: str | None = None
    quality_flags: list[dict[str, Any]] | None = None


class BatRunResponse(BaseModel):
    """Summary of one bat run. The track itself lives in the artefact."""

    correlation_id: str
    person_id: uuid.UUID | None
    model_version: str
    #: The labelled corpus the detector was trained on; None when untrained.
    dataset_version: str | None
    frame_count: int
    #: Frames in which the bat was actually found.
    frames_detected: int
    mean_confidence: float | None
    #: True when detection was too poor for M10 to trust (FR-M07-05).
    provisional: bool
    #: ok | provisional | rejected
    quality: str
    #: Object-storage ref for the bat track; None when rejected.
    artefact_ref: str | None
    created_at: datetime


def _to_response(row: dict[str, Any]) -> BatRunResponse:
    return BatRunResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        model_version=row["model_version"],
        dataset_version=row["dataset_version"],
        frame_count=row["frame_count"],
        frames_detected=row["frames_detected"],
        mean_confidence=row["mean_confidence"],
        provisional=row["provisional"],
        quality=row["quality"],
        artefact_ref=row["artefact_ref"],
        created_at=row["created_at"],
    )


@internal_router.post("/compute", response_model=BatRunResponse)
async def compute(
    body: ComputeRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BatRunResponse:
    """Detect the bat on a clip; persists + publishes exactly as the consumer does."""
    tenant_id = require_tenant_id()
    row = await process_normalized(
        session_factory=deps.session_factory,
        detector=deps.detector,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        pose_client=deps.pose_client,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
        normalized_ref=body.normalized_ref,
        camera_angle=body.camera_angle,
        spatial_confidence=body.spatial_confidence,
        quality_flags=body.quality_flags,
    )
    return _to_response(row)


@bat_router.get("/{correlation_id}", response_model=BatRunResponse)
async def read_bat_run(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BatRunResponse:
    """Bat-run summary for a clip. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_bat_run(session, correlation_id)
    if row is None:
        raise NotFound("bat run not found")
    return _to_response(row)
