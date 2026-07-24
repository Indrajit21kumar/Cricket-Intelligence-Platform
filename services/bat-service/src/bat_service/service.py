"""Bat application service (M07 Step 7).

Where the pure pipeline meets I/O: load the clip and M06's pose, run the
detector, persist the track artefact + a bat_runs summary, route consented
frames to the annotation queue, and publish ``bat.tracked``.

Both entry points share it — the ``video.normalized`` consumer (the production
trigger) and ``POST /internal/bat/compute`` (tests / reprocessing).

Idempotent per correlation_id: the bat_runs upsert is keyed on
(tenant_id, correlation_id), the artefact key is correlation-namespaced, the
annotation queue conflicts on (tenant, correlation, frame), and the published
envelope carries a correlation-based idempotency key (NFR-M07-04, AC-M07-05).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from bat_service.deps import Deps
from bat_service.domain.annotation import enqueue_frames, select_frames
from bat_service.domain.artefact import ArtefactStore, artefact_key, serialise_track
from bat_service.domain.bat import QUALITY_REJECTED
from bat_service.domain.bat_runs import upsert_bat_run
from bat_service.domain.clip import ClipLoader
from bat_service.domain.detector import BatDetector
from bat_service.domain.pipeline import compute_bat_run
from bat_service.domain.pose_client import PoseClient
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer

TOPIC_VIDEO_NORMALIZED = "video.normalized"
TOPIC_BAT_TRACKED = "bat.tracked"
TOPIC_BAT_DLQ = "bat.dlq"
CONSUMER_GROUP = "bat-detection"


async def process_normalized(
    *,
    session_factory: async_sessionmaker[Any],
    detector: BatDetector,
    clip_loader: ClipLoader,
    artefact_store: ArtefactStore,
    pose_client: PoseClient,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    normalized_ref: str,
    camera_angle: str | None = None,
    spatial_confidence: str | None = None,
    quality_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Detect the bat on a normalised clip: compute -> persist -> publish."""
    geo = await clip_loader.load(normalized_ref)
    # M06's wrists disambiguate the batter's bat. Its absence is expected, not
    # exceptional: M06 rejects clips it cannot track, and M07 still runs.
    pose = await pose_client.load(correlation_id)
    result = compute_bat_run(
        detector,
        frame_count=geo.frame_count,
        width=geo.width,
        height=geo.height,
        pose=pose,
    )

    artefact_ref: str | None = None
    if result.degradation.quality != QUALITY_REJECTED:
        key = artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        artefact_ref = await artefact_store.save(
            key,
            serialise_track(result.frames, angles=result.angles, plane=result.plane),
        )

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_bat_run(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            model_version=result.model_version,
            dataset_version=result.dataset_version,
            frame_count=result.frame_count,
            frames_detected=result.degradation.frames_detected,
            mean_confidence=(
                result.degradation.mean_confidence if result.degradation.frames_detected else None
            ),
            provisional=result.degradation.provisional,
            quality=result.degradation.quality,
            artefact_ref=artefact_ref,
        )

        # The flywheel (FR-M07-08). Runs inside the same tenant scope so the
        # queue rows land under the right RLS policy, and refuses by default:
        # enqueue_frames re-checks training consent regardless of what got the
        # clip this far.
        enqueue = await enqueue_frames(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            frames=select_frames(result.frames),
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"bat.tracked:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "artefact_ref": artefact_ref,
            "model_version": result.model_version,
            "dataset_version": result.dataset_version,
            "frame_count": result.frame_count,
            "frames_detected": result.degradation.frames_detected,
            "mean_confidence": (
                result.degradation.mean_confidence if result.degradation.frames_detected else None
            ),
            # M10 keys its provisional handling off this pair.
            "provisional": result.degradation.provisional,
            "quality": result.degradation.quality,
            "degradation_reason": result.degradation.reason,
            "downswing_failure_ratio": result.degradation.downswing_failure_ratio,
            # How the bat was attributed: a run tracked mostly by continuity is
            # weaker evidence than one tracked by the batter's hands.
            "hand_associated_frames": result.hand_associated_frames,
            # Whether these coordinates share M06's stance origin, or are only
            # clip-relative because no pose was available. M10 must not mix a
            # clip_relative bat track with body geometry.
            "frame_basis": result.frame_basis,
            "swing_plane": (
                {
                    "inclination_degrees": result.plane.inclination_degrees,
                    "linearity": result.plane.linearity,
                    "confidence": result.plane.confidence,
                    "provenance": result.plane.provenance,
                }
                if result.plane is not None
                else None
            ),
            # M05 context carried through for downstream consumers.
            "camera_angle": camera_angle,
            "spatial_confidence": spatial_confidence,
            "quality_flags": quality_flags or [],
            "annotation_frames_queued": enqueue.queued,
        },
    )
    await event_bus.publish(TOPIC_BAT_TRACKED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_video_normalized(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a video.normalized envelope into a bat run."""
    p = envelope.payload
    await process_normalized(
        session_factory=deps.session_factory,
        detector=deps.detector,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        pose_client=deps.pose_client,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(p.get("person_id")),
        normalized_ref=str(p.get("normalized_ref", "")),
        camera_angle=p.get("camera_angle"),
        spatial_confidence=p.get("spatial_confidence"),
        quality_flags=p.get("quality_flags"),
    )


def build_bat_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over video.normalized -> bat runs."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_video_normalized(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_VIDEO_NORMALIZED,
        dlq_topic=TOPIC_BAT_DLQ,
        group_id=CONSUMER_GROUP,
    )
