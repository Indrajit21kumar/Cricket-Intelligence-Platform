"""Video Intelligence API routes — M05.

- Step 2: signed-URL upload + validation + M03 entitlement gate.

M05 is tenant-scoped: the tenant comes from the ``X-Tenant-ID`` header
(bound by cip-core middleware); ``person_id`` (the player the clip is of) is
in the request body. ``correlation_id`` threads the clip through the pipeline
and is the idempotency anchor.

Endpoints:
  POST /v1/videos              create ingestion + return a signed upload URL
  POST /v1/videos/{id}/complete  mark upload complete
  GET  /v1/videos/{id}          ingestion status

Later steps add preprocessing (3), angle (4), calibration (5), quality gate
(6), publish + metering (7), and the capture-guidance / quality API (8).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import (
    AuthenticatedPrincipal,
    Forbidden,
    NotFound,
    Unprocessable,
    get_correlation_id,
    new_correlation_id,
    require_authenticated,
    require_tenant_id,
)
from cip_data import tenant_session
from video_service.deps import Deps, get_deps
from video_service.domain.ingestions import (
    create_ingestion,
    get_ingestion,
)
from video_service.domain.pipeline import run_pipeline
from video_service.domain.processing_results import get_processing_result
from video_service.domain.validation import validate_upload

videos_router = APIRouter(prefix="/v1/videos", tags=["videos"])


class CreateVideoRequest(BaseModel):
    person_id: uuid.UUID = Field(..., description="The player the clip is of (M02 person)")
    source_type: str = Field(..., description="mobile | dslr | nets | match")
    content_type: str = Field(..., description="video/mp4 | video/quicktime | video/webm")
    size_bytes: int | None = Field(None, ge=0, description="Declared upload size")


class CreateVideoResponse(BaseModel):
    ingestion_id: uuid.UUID
    correlation_id: str
    raw_ref: str
    upload_url: str
    expires_in: int
    status: str


class ProcessingView(BaseModel):
    normalized_ref: str | None = None
    frame_count: int | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    duration_s: float | None = None


class IngestionView(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    correlation_id: str
    source_type: str
    status: str
    content_type: str | None = None
    size_bytes: int | None = None
    created_at: datetime | None = None
    processing: ProcessingView | None = None


def _ingestion_view(row: dict[str, Any]) -> IngestionView:
    return IngestionView(
        id=row["id"],
        person_id=row["person_id"],
        correlation_id=str(row["correlation_id"]),
        source_type=str(row["source_type"]),
        status=str(row["status"]),
        content_type=row.get("content_type"),
        size_bytes=row.get("size_bytes"),
        created_at=row.get("created_at"),
    )


def _correlation() -> str:
    return get_correlation_id() or new_correlation_id()


@videos_router.post("", response_model=CreateVideoResponse, status_code=201)
async def create_video(
    body: CreateVideoRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> CreateVideoResponse:
    """Create an ingestion + return a signed upload URL.

    Order (M05 §5/§8): validate the request, then check the analysis
    entitlement with M03 (deny over-quota), then mint the signed URL and
    persist the ingestion. No GPU / preprocessing happens here.
    """
    _ = principal
    tenant_id = require_tenant_id()

    # 1. Server-side validation (FR-M05-01).
    reasons = validate_upload(
        content_type=body.content_type,
        source_type=body.source_type,
        size_bytes=body.size_bytes,
    )
    if reasons:
        raise Unprocessable("Upload failed validation", details={"reasons": reasons})

    # 2. Entitlement gate — M05 is the first billable stage (FR-M05-02, AC-M05-04).
    decision = await deps.entitlement_client.check_analysis_quota(tenant_id=tenant_id)
    if not decision.allowed:
        raise Forbidden(
            "Analysis quota exhausted for this subscription",
            details={"reason": decision.reason},
        )

    # 3. Mint the signed URL + persist the ingestion (idempotent on correlation).
    correlation_id = _correlation()
    ingestion_id = uuid.uuid4()
    signed = deps.storage.create_upload_url(
        tenant_id=tenant_id,
        person_id=body.person_id,
        ingestion_id=ingestion_id,
        content_type=body.content_type,
    )
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        row, _created = await create_ingestion(
            session,
            tenant_id=tenant_id,
            person_id=body.person_id,
            correlation_id=correlation_id,
            source_type=body.source_type,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
            raw_ref=signed.raw_ref,
        )

    return CreateVideoResponse(
        ingestion_id=row["id"],
        correlation_id=str(row["correlation_id"]),
        raw_ref=str(row["raw_ref"]),
        upload_url=signed.upload_url,
        expires_in=signed.expires_in,
        status=str(row["status"]),
    )


class CompleteResponse(BaseModel):
    ingestion_id: uuid.UUID
    status: str
    normalized_ref: str
    frame_count: int
    fps: float


@videos_router.post("/{ingestion_id}/complete", response_model=CompleteResponse)
async def complete_upload(
    ingestion_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> CompleteResponse:
    """Mark the upload complete and run the processing pipeline.

    Verifies the object is present, then runs preprocessing (Step 3). Later
    steps extend the pipeline with angle detection, calibration, the quality
    gate, and publishing.
    """
    _ = principal
    tenant_id = require_tenant_id()
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        ingestion = await get_ingestion(session, ingestion_id)
        if ingestion is None:
            raise NotFound("Ingestion not found")
        if not await deps.storage.object_exists(str(ingestion["raw_ref"])):
            raise Unprocessable(
                "Uploaded object not found in storage",
                details={"reason": "object_missing"},
            )
        outcome = await run_pipeline(
            session,
            tenant_id=tenant_id,
            ingestion=ingestion,
            processor=deps.video_processor,
        )

    return CompleteResponse(
        ingestion_id=outcome.ingestion_id,
        status=outcome.status,
        normalized_ref=outcome.normalized_ref,
        frame_count=outcome.frame_count,
        fps=outcome.fps,
    )


@videos_router.get("/{ingestion_id}", response_model=IngestionView)
async def get_video(
    ingestion_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> IngestionView:
    """Ingestion status + processing details (RLS scopes it to the tenant)."""
    _ = principal
    tenant_id = require_tenant_id()
    async with tenant_session(deps.session_factory, tenant_id=tenant_id) as session:
        ingestion = await get_ingestion(session, ingestion_id)
        if ingestion is None:
            raise NotFound("Ingestion not found")
        processing = await get_processing_result(session, ingestion_id)
    view = _ingestion_view(ingestion)
    if processing is not None:
        view = view.model_copy(
            update={
                "processing": ProcessingView(
                    normalized_ref=processing["normalized_ref"],
                    frame_count=processing["frame_count"],
                    fps=processing["fps"],
                    width=processing["width"],
                    height=processing["height"],
                    duration_s=processing["duration_s"],
                )
            }
        )
    return view
