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
from cip_events import EventEnvelope
from video_service.deps import Deps, get_deps
from video_service.domain.calibrations import get_calibration
from video_service.domain.ingestions import (
    create_ingestion,
    get_ingestion,
)
from video_service.domain.pipeline import run_pipeline
from video_service.domain.processing_results import get_processing_result
from video_service.domain.validation import validate_upload

videos_router = APIRouter(prefix="/v1/videos", tags=["videos"])

# The event M05 publishes to the downstream engines (M06-M09).
TOPIC_VIDEO_NORMALIZED = "video.normalized"


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


class CalibrationView(BaseModel):
    camera_angle: str | None = None
    pixel_to_meter: float | None = None
    spatial_confidence: str | None = None
    depth_estimated: bool | None = None
    method: str | None = None


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
    calibration: CalibrationView | None = None


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


class QualityFlagView(BaseModel):
    code: str
    severity: str  # fail | flag
    message: str


class CompleteResponse(BaseModel):
    ingestion_id: uuid.UUID
    status: str
    normalized_ref: str
    frame_count: int
    fps: float
    camera_angle: str
    angle_supported: bool
    angle_recommendation: str | None = None
    pixel_to_meter: float | None = None
    spatial_confidence: str
    depth_estimated: bool
    calibration_method: str
    admitted: bool
    flags: list[QualityFlagView]
    usage_recorded: bool = False


@videos_router.post("/{ingestion_id}/complete", response_model=CompleteResponse)
async def complete_upload(
    ingestion_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> CompleteResponse:
    """Mark the upload complete and run the processing pipeline.

    Runs preprocess -> angle -> calibrate -> quality gate. A clip that
    hard-fails the gate is REJECTED (422 + actionable reasons); the rejection
    + flags are persisted first, so the client can also fetch them later. An
    admitted clip returns 200 with metadata + any soft flags.
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
            profile_client=deps.profile_client,
        )

    flag_views = [
        QualityFlagView(code=f.code, severity=f.severity, message=f.message) for f in outcome.flags
    ]

    # Hard-fail -> 422 with actionable reasons (AC-M05-02). The rejection +
    # flags are already committed above, so this is recorded, not lost.
    if not outcome.admitted:
        raise Unprocessable(
            "Clip rejected by the quality gate",
            details={
                "reasons": [f.code for f in outcome.flags if f.severity == "fail"],
                "flags": [f.model_dump() for f in flag_views],
            },
        )

    # --- Admitted (Step 7): meter usage + publish video.normalized --------
    # Metering is exactly-once per clip (idempotency key = correlation_id), so
    # a re-delivered /complete never double-counts (AC-M05-05, NFR-M05-05).
    usage_recorded = await deps.entitlement_client.record_analysis_usage(
        tenant_id=tenant_id,
        idempotency_key=f"analysis.consumed:{outcome.correlation_id}",
    )
    # Publish the normalised clip + calibration + soft flags for M06-M09.
    envelope = EventEnvelope(
        correlation_id=outcome.correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"video.normalized:{outcome.ingestion_id}",
        payload={
            "ingestion_id": str(outcome.ingestion_id),
            "person_id": str(outcome.person_id),
            "normalized_ref": outcome.normalized_ref,
            "camera_angle": outcome.camera_angle,
            "pixel_to_meter": outcome.pixel_to_meter,
            "spatial_confidence": outcome.spatial_confidence,
            "depth_estimated": outcome.depth_estimated,
            "calibration_method": outcome.calibration_method,
            "quality_flags": [f.model_dump() for f in flag_views],
        },
    )
    await deps.event_bus.publish(TOPIC_VIDEO_NORMALIZED, envelope)

    return CompleteResponse(
        ingestion_id=outcome.ingestion_id,
        status=outcome.status,
        normalized_ref=outcome.normalized_ref,
        frame_count=outcome.frame_count,
        fps=outcome.fps,
        camera_angle=outcome.camera_angle,
        angle_supported=outcome.angle_supported,
        angle_recommendation=outcome.angle_recommendation,
        pixel_to_meter=outcome.pixel_to_meter,
        spatial_confidence=outcome.spatial_confidence,
        depth_estimated=outcome.depth_estimated,
        calibration_method=outcome.calibration_method,
        admitted=outcome.admitted,
        flags=flag_views,
        usage_recorded=usage_recorded,
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
        calibration = await get_calibration(session, ingestion_id)
    updates: dict[str, object] = {}
    if processing is not None:
        updates["processing"] = ProcessingView(
            normalized_ref=processing["normalized_ref"],
            frame_count=processing["frame_count"],
            fps=processing["fps"],
            width=processing["width"],
            height=processing["height"],
            duration_s=processing["duration_s"],
        )
    if calibration is not None:
        updates["calibration"] = CalibrationView(
            camera_angle=calibration["camera_angle"],
            pixel_to_meter=calibration["pixel_to_meter"],
            spatial_confidence=calibration["spatial_confidence"],
            depth_estimated=calibration["depth_estimated"],
            method=calibration["method"],
        )
    return _ingestion_view(ingestion).model_copy(update=updates)
