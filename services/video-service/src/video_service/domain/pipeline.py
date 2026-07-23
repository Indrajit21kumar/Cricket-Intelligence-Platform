"""Processing pipeline orchestrator (M05, grows across Steps 3-7).

One clip flows through: preprocess -> [angle -> calibrate -> quality gate ->
publish]. Each step adds a stage; Step 3 implements preprocessing only. The
whole pipeline runs on CPU and the quality gate (Step 6) runs BEFORE any GPU
stage (NFR-M05-02) — that ordering is why preprocessing is cheap and the gate
protects downstream GPU cost.

``run_pipeline`` is idempotent per ingestion (safe re-delivery, NFR-M05-05):
processing_results upserts on ingestion_id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from video_service.domain.angle import classify_angle
from video_service.domain.calibrations import upsert_calibration
from video_service.domain.ingestions import STATUS_PROCESSING, set_status
from video_service.domain.processing_results import save_processing_result
from video_service.domain.processor import ClipMeasurements, VideoProcessor


@dataclass(slots=True)
class PipelineOutcome:
    """Accumulates as the pipeline runs; later steps fill more fields."""

    ingestion_id: uuid.UUID
    status: str
    normalized_ref: str
    frame_count: int
    fps: float
    measurements: ClipMeasurements
    # Step 4 — camera angle.
    camera_angle: str = "other"
    angle_supported: bool = False
    angle_recommendation: str | None = None


async def run_pipeline(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ingestion: dict[str, Any],
    processor: VideoProcessor,
) -> PipelineOutcome:
    """Run the preprocessing stage for an uploaded clip (Step 3).

    Later steps extend this with angle detection, calibration, the quality
    gate, and publishing.
    """
    ingestion_id: uuid.UUID = ingestion["id"]
    raw_ref: str = ingestion["raw_ref"]

    await set_status(session, ingestion_id, STATUS_PROCESSING)

    # --- Preprocess (Step 3) ----------------------------------------------
    result = await processor.preprocess(raw_ref=raw_ref)
    m = result.measurements
    await save_processing_result(
        session,
        tenant_id=tenant_id,
        ingestion_id=ingestion_id,
        normalized_ref=result.normalized_ref,
        frame_count=m.frame_count,
        fps=m.fps,
        width=m.width,
        height=m.height,
        duration_s=m.duration_s,
    )

    # --- Camera angle (Step 4) --------------------------------------------
    angle = classify_angle(angle_hint=m.angle_hint, angle_confidence=m.angle_confidence)
    # Persist the angle now (spatial_confidence stays 'low' provisionally;
    # Step 5 computes the real value + pixel_to_meter from stump/height).
    await upsert_calibration(
        session,
        tenant_id=tenant_id,
        ingestion_id=ingestion_id,
        camera_angle=angle.camera_angle,
    )

    return PipelineOutcome(
        ingestion_id=ingestion_id,
        status=STATUS_PROCESSING,
        normalized_ref=result.normalized_ref,
        frame_count=m.frame_count,
        fps=m.fps,
        measurements=m,
        camera_angle=angle.camera_angle,
        angle_supported=angle.supported,
        angle_recommendation=angle.recommendation,
    )
