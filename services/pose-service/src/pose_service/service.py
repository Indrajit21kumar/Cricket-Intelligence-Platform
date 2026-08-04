"""Pose application service (M06 Steps 2 + 6).

The one place the pure compute (:func:`compute_pose_run`) meets I/O: load the
clip, run the pipeline, persist the keypoint artefact + a pose_runs summary,
and publish ``pose.keypoints``. Both entry points share it:

- the ``video.normalized`` consumer (production trigger), via
  :func:`build_pose_consumer`; and
- ``POST /internal/pose/compute`` (sync entry for tests / reprocessing).

Idempotent per correlation_id: the pose_runs upsert is keyed on
(tenant_id, correlation_id), the artefact key is correlation-namespaced, and
the published envelope carries a correlation-based idempotency key — so a
re-delivered clip never duplicates (NFR-M06-04, AC-M06-05).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from pose_service.deps import Deps
from pose_service.domain.artefact import ArtefactStore, artefact_key, serialise_frames
from pose_service.domain.clip import ClipLoader
from pose_service.domain.keypoints import QUALITY_REJECTED
from pose_service.domain.model import PoseModel
from pose_service.domain.pipeline import compute_pose_run
from pose_service.domain.pose_runs import upsert_pose_run

TOPIC_VIDEO_NORMALIZED = "video.normalized"
TOPIC_POSE_KEYPOINTS = "pose.keypoints"
TOPIC_POSE_DLQ = "pose.dlq"
CONSUMER_GROUP = "pose-engine"


async def process_normalized(
    *,
    session_factory: async_sessionmaker[Any],
    model: PoseModel,
    clip_loader: ClipLoader,
    artefact_store: ArtefactStore,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    normalized_ref: str,
    camera_angle: str | None = None,
    spatial_confidence: str | None = None,
    depth_estimated: bool = True,
    quality_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run pose on a normalised clip: compute → persist → publish. Returns the run."""
    geo = await clip_loader.load(normalized_ref)
    result = compute_pose_run(
        model,
        frame_count=geo.frame_count,
        width=geo.width,
        height=geo.height,
        depth_estimated=depth_estimated,
        frames=geo.frames,
    )

    # Large keypoint sequence -> object storage; DB keeps the summary.
    artefact_ref: str | None = None
    if result.frames:
        key = artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        artefact_ref = await artefact_store.save(
            key,
            serialise_frames(
                result.frames,
                origin_x=result.origin_x,
                origin_y=result.origin_y,
                scale=result.scale,
            ),
        )

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_pose_run(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            model_version=result.model_version,
            frame_count=result.frame_count,
            mean_confidence=result.mean_confidence if result.frames else None,
            subject_status=result.subject_status,
            quality=result.quality,
            artefact_ref=artefact_ref,
            depth_estimated=result.depth_estimated,
        )

    # Publish for M09/M10 — even a rejection is announced (quality tells them),
    # propagating M05's calibration + quality context (FR-M06-08). A rejected
    # run also carries the reason as an upper-case code (AC-M06-02) so a
    # consumer can branch on it without parsing the status string.
    rejection_code = result.subject_status.upper() if result.quality == QUALITY_REJECTED else None
    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"pose.keypoints:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "artefact_ref": artefact_ref,
            "model_version": result.model_version,
            "frame_count": result.frame_count,
            "mean_confidence": result.mean_confidence if result.frames else None,
            "subject_status": result.subject_status,
            "quality": result.quality,
            "rejection_code": rejection_code,
            "depth_estimated": result.depth_estimated,
            # The CIP-frame transform, so M07/M08/M10 can place the bat, the
            # ball and their derived geometry in the same frame as the body.
            "frame": {
                "origin_x": result.origin_x,
                "origin_y": result.origin_y,
                "scale": result.scale,
                "y_up": True,
            },
            "camera_angle": camera_angle,
            "spatial_confidence": spatial_confidence,
            "quality_flags": quality_flags or [],
        },
    )
    await event_bus.publish(TOPIC_POSE_KEYPOINTS, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_video_normalized(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a video.normalized envelope into a pose run."""
    p = envelope.payload
    await process_normalized(
        session_factory=deps.session_factory,
        model=deps.model,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(p.get("person_id")),
        normalized_ref=str(p.get("normalized_ref", "")),
        camera_angle=p.get("camera_angle"),
        spatial_confidence=p.get("spatial_confidence"),
        # Monocular unless M05 says otherwise — never silently claim measured depth.
        depth_estimated=bool(p.get("depth_estimated", True)),
        quality_flags=p.get("quality_flags"),
    )


def build_pose_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over video.normalized -> pose runs."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_video_normalized(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_VIDEO_NORMALIZED,
        dlq_topic=TOPIC_POSE_DLQ,
        group_id=CONSUMER_GROUP,
    )
