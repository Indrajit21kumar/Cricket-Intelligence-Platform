"""Ball application service (M08 Step 7).

Where the pure pipeline meets I/O: load the clip and M07's bat track, run the
tracker, persist the artefact + a ball_runs summary, route consented deliveries
to the annotation queue, and publish ``ball.events``.

Both entry points share it — the ``video.normalized`` consumer (the production
trigger) and ``POST /internal/ball/compute`` (tests / reprocessing).

Idempotent per correlation_id at every layer: the ball_runs upsert is keyed on
(tenant_id, correlation_id), the artefact key is correlation-namespaced, the
annotation queue conflicts on (tenant, correlation, modality, frame), and the
envelope carries a correlation-based idempotency key (NFR-M08-04, AC-M08-06).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from ball_service.deps import Deps
from ball_service.domain.artefact import (
    ArtefactStore,
    artefact_key,
    events_payload,
    serialise_track,
)
from ball_service.domain.ball import QUALITY_REJECTED
from ball_service.domain.ball_runs import upsert_ball_run
from ball_service.domain.bat_client import BatClient
from ball_service.domain.clip import ClipLoader
from ball_service.domain.pipeline import compute_ball_run
from ball_service.domain.selection import select_frames
from ball_service.domain.tracker import BallTracker
from cip_annotation import MODALITY_BALL, enqueue_frames
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer

TOPIC_VIDEO_NORMALIZED = "video.normalized"
TOPIC_BALL_EVENTS = "ball.events"
TOPIC_BALL_DLQ = "ball.dlq"
CONSUMER_GROUP = "ball-tracking"


async def process_normalized(
    *,
    session_factory: async_sessionmaker[Any],
    tracker: BallTracker,
    clip_loader: ClipLoader,
    artefact_store: ArtefactStore,
    bat_client: BatClient,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    normalized_ref: str,
    fps: float | None = None,
    camera_angle: str | None = None,
    pixel_to_meter: float | None = None,
    spatial_confidence: str | None = None,
    quality_flags: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Track the ball on a normalised clip: compute -> persist -> publish."""
    geo = await clip_loader.load(normalized_ref)
    # M07's bat gives contact its proximity half. Absent is expected, not
    # exceptional: M07 rejects clips it cannot track, and M08 still runs —
    # contact simply is not claimed.
    bat = await bat_client.load(correlation_id)

    result = compute_ball_run(
        tracker,
        frame_count=geo.frame_count,
        width=geo.width,
        height=geo.height,
        fps=fps,
        pixel_to_meter=pixel_to_meter,
        spatial_confidence=spatial_confidence,
        camera_angle=camera_angle,
        quality_flags=quality_flags,
        bat=bat,
    )

    events = result.events
    artefact_ref: str | None = None
    if result.failsafe.quality != QUALITY_REJECTED:
        key = artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        artefact_ref = await artefact_store.save(key, serialise_track(result.track, events=events))

    payload_events = events_payload(events)

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_ball_run(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            model_version=result.model_version,
            dataset_version=result.dataset_version,
            frame_count=result.frame_count,
            frames_detected=result.frames_detected,
            track_confidence=result.failsafe.track_confidence,
            timing_reference=events.timing_reference,
            conditions_met=result.failsafe.conditions_met,
            events=payload_events,
            quality=result.failsafe.quality,
            artefact_ref=artefact_ref,
        )

        # The flywheel (FR-M08-09). Inside the tenant scope so rows land under
        # the right RLS policy; enqueue_frames re-checks training consent
        # regardless of what got the clip this far.
        enqueue = await enqueue_frames(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            frames=select_frames(result),
            modality=MODALITY_BALL,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"ball.events:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "artefact_ref": artefact_ref,
            "model_version": result.model_version,
            "dataset_version": result.dataset_version,
            "frame_count": result.frame_count,
            "frames_detected": result.frames_detected,
            # M10 reads timing_reference to choose release-relative or absolute
            # timing, and track_confidence to decide the bat-only fallback.
            "track_confidence": result.failsafe.track_confidence,
            "quality": result.failsafe.quality,
            "conditions_met": result.failsafe.conditions_met,
            "condition_profile": result.conditions.profile,
            "degradation_reasons": list(result.failsafe.reasons),
            # Absent events are absent KEYS inside this object.
            "events": payload_events,
            # M05 context carried through.
            "camera_angle": camera_angle,
            "fps": fps,
            "spatial_confidence": spatial_confidence,
            "quality_flags": quality_flags or [],
            "annotation_frames_queued": enqueue.queued,
        },
    )
    await event_bus.publish(TOPIC_BALL_EVENTS, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


def _parse_float(raw: object) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


async def handle_video_normalized(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a video.normalized envelope into a ball run."""
    p = envelope.payload
    await process_normalized(
        session_factory=deps.session_factory,
        tracker=deps.tracker,
        clip_loader=deps.clip_loader,
        artefact_store=deps.artefact_store,
        bat_client=deps.bat_client,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(p.get("person_id")),
        normalized_ref=str(p.get("normalized_ref", "")),
        fps=_parse_float(p.get("fps")),
        camera_angle=p.get("camera_angle"),
        pixel_to_meter=_parse_float(p.get("pixel_to_meter")),
        spatial_confidence=p.get("spatial_confidence"),
        quality_flags=p.get("quality_flags"),
    )


def build_ball_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over video.normalized -> ball runs."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_video_normalized(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_VIDEO_NORMALIZED,
        dlq_topic=TOPIC_BALL_DLQ,
        group_id=CONSUMER_GROUP,
    )
