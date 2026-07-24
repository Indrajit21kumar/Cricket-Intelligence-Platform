"""Pose Engine API routes — M06 §10.

M06's production trigger is the ``video.normalized`` event, not a request:
the consumer (see :mod:`pose_service.service`) drives the same code path.
These endpoints exist alongside it:

  POST /internal/pose/compute   sync compute for reprocessing / tests
  GET  /v1/pose/{correlationId} the run summary for a clip

Tenant-scoped (RLS): the tenant comes from the ``X-Tenant-ID`` header bound
by cip-core middleware, and ``correlation_id`` — threaded from M05 — is the
key everything downstream joins on.
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
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session
from pose_service.deps import Deps, get_deps
from pose_service.domain.keypoints import QUALITY_REJECTED
from pose_service.domain.pose_runs import get_pose_run
from pose_service.service import process_normalized

pose_router = APIRouter(prefix="/v1/pose", tags=["pose"])
internal_router = APIRouter(prefix="/internal/pose", tags=["internal"])


class ComputeRequest(BaseModel):
    """The M05 ``video.normalized`` payload, as a request body."""

    correlation_id: str = Field(..., min_length=1, max_length=64)
    normalized_ref: str = Field(..., min_length=1, description="Normalised-clip object ref")
    person_id: uuid.UUID | None = Field(None, description="The player the clip is of")
    camera_angle: str | None = None
    spatial_confidence: str | None = None
    #: True for monocular capture (the norm) — carried from M05, never re-decided.
    depth_estimated: bool = True
    quality_flags: list[dict[str, Any]] | None = None


class PoseRunResponse(BaseModel):
    """Summary of one pose run. The keypoints themselves live in the artefact."""

    correlation_id: str
    person_id: uuid.UUID | None
    model_version: str
    frame_count: int
    #: Mean per-joint confidence across tracked frames; None when rejected.
    mean_confidence: float | None
    #: tracked | multi_subject_ambiguous | no_subject
    subject_status: str
    #: ok | provisional | rejected
    quality: str
    #: Why a rejected run was rejected, e.g. MULTI_SUBJECT_AMBIGUOUS. None otherwise.
    rejection_code: str | None
    #: Object-storage ref for the keypoint sequence; None when rejected.
    artefact_ref: str | None
    #: True when Z was inferred from a single camera (monocular depth).
    depth_estimated: bool
    created_at: datetime


def _to_response(row: dict[str, Any]) -> PoseRunResponse:
    rejected = row["quality"] == QUALITY_REJECTED
    return PoseRunResponse(
        correlation_id=row["correlation_id"],
        person_id=row["person_id"],
        model_version=row["model_version"],
        frame_count=row["frame_count"],
        mean_confidence=row["mean_confidence"],
        subject_status=row["subject_status"],
        quality=row["quality"],
        rejection_code=str(row["subject_status"]).upper() if rejected else None,
        artefact_ref=row["artefact_ref"],
        depth_estimated=row["depth_estimated"],
        created_at=row["created_at"],
    )


@internal_router.post("/compute", response_model=PoseRunResponse)
async def compute(
    body: ComputeRequest,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> PoseRunResponse:
    """Run pose on a normalised clip; persists + publishes exactly as the consumer does."""
    tenant_id = require_tenant_id()
    row = await process_normalized(
        session_factory=deps.session_factory,
        model=deps.model,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        correlation_id=body.correlation_id,
        person_id=body.person_id,
        normalized_ref=body.normalized_ref,
        camera_angle=body.camera_angle,
        spatial_confidence=body.spatial_confidence,
        depth_estimated=body.depth_estimated,
        quality_flags=body.quality_flags,
    )
    return _to_response(row)


@pose_router.get("/{correlation_id}", response_model=PoseRunResponse)
async def read_pose_run(
    correlation_id: str,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> PoseRunResponse:
    """Pose-run summary for a clip. RLS scopes the lookup to the caller's tenant."""
    require_tenant_id()
    async with tenant_session(deps.session_factory) as session:
        row = await get_pose_run(session, correlation_id)
    if row is None:
        raise NotFound("pose run not found")
    return _to_response(row)
