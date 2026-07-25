"""Shot application service (M09 Step 5).

Where the pure pipeline meets I/O: load pose (+ optional bat/ball), classify,
persist a shot_runs row, route consented samples to the annotation queue, and
publish ``shot.classified``.

Trigger + fan-in: M09 is the first module driven by a DERIVED event
(``pose.keypoints``), not raw video. Pose is required — M06 is a hard
dependency — so the consumer keys off it and FETCHES bat/ball by
correlation_id, degrading to pose-only when they are absent (FR-M09-04). A
clip M06 rejected produces no pose.keypoints and so no shot run, which is
correct: there is nothing to classify without a body.

Both entry points share this: the ``pose.keypoints`` consumer (production
trigger) and ``POST /internal/shot/classify`` (tests / reprocessing).

Idempotent per correlation_id: the shot_runs upsert is keyed on
(tenant_id, correlation_id), the annotation queue conflicts on
(tenant, correlation, modality, frame), and the envelope carries a
correlation-based idempotency key (NFR-M09-03, AC-M09-06).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_annotation import MODALITY_SHOT, enqueue_frames
from cip_data import tenant_session
from cip_events import EventBus, EventEnvelope, IdempotencyStore, IdempotentConsumer
from shot_service.deps import Deps
from shot_service.domain.classifier import ShotClassifier
from shot_service.domain.pipeline import classify_shot
from shot_service.domain.selection import select_frames
from shot_service.domain.shot_runs import upsert_shot_run
from shot_service.domain.sources import BallSource, BatSource, PoseSource

TOPIC_POSE_KEYPOINTS = "pose.keypoints"
TOPIC_SHOT_CLASSIFIED = "shot.classified"
TOPIC_SHOT_DLQ = "shot.dlq"
CONSUMER_GROUP = "shot-recognition"


async def process_stroke(
    *,
    session_factory: async_sessionmaker[Any],
    classifier: ShotClassifier,
    pose_source: PoseSource,
    bat_source: BatSource,
    ball_source: BallSource,
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    camera_angle: str | None = None,
) -> dict[str, Any] | None:
    """Classify one stroke: fetch -> classify -> persist -> publish.

    Returns None when M06 produced no usable pose — there is nothing to
    classify, so no run is created and nothing is published.
    """
    pose = await pose_source.load(correlation_id)
    if pose is None or pose.frame_count == 0:
        return None

    # Bat and ball are optional; their absence is the pose-only path.
    bat = await bat_source.load(correlation_id)
    ball = await ball_source.load(correlation_id)

    run = classify_shot(classifier, pose=pose, bat=bat, ball=ball)
    result = run.result

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await upsert_shot_run(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            model_version=run.model_version,
            dataset_version=run.dataset_version,
            shot_class=result.shot_class,
            shot_confidence=result.shot_confidence,
            phase_boundaries=result.phases.as_dict(),
            phase_method=result.phases.method,
            signals_used=list(result.signals_used),
            quality=result.quality,
        )

        # The flywheel (FR-M09-08): abstentions and low-confidence calls are
        # the samples worth labelling. Re-checks training consent regardless.
        enqueue = await enqueue_frames(
            session,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            person_id=person_id,
            frames=select_frames(run),
            modality=MODALITY_SHOT,
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"shot.classified:{correlation_id}",
        payload={
            "correlation_id": correlation_id,
            "person_id": str(person_id) if person_id else None,
            "model_version": run.model_version,
            "dataset_version": run.dataset_version,
            # M10 selects benchmark ranges off shot_class, applying generic
            # handling when it is 'unclassified'.
            "shot_class": result.shot_class,
            "shot_confidence": result.shot_confidence,
            # Frame indices for the five phases + how impact was anchored.
            "phase_boundaries": result.phases.as_dict(),
            "phase_method": result.phases.method,
            "signals_used": list(result.signals_used),
            "quality": result.quality,
            "camera_angle": camera_angle,
            "annotation_frames_queued": enqueue.queued,
        },
    )
    await event_bus.publish(TOPIC_SHOT_CLASSIFIED, envelope)
    return row


def _parse_person(raw: object) -> uuid.UUID | None:
    if not raw:
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        return None


async def handle_pose_keypoints(deps: Deps, envelope: EventEnvelope) -> None:
    """Consumer handler: turn a pose.keypoints envelope into a shot run."""
    p = envelope.payload
    await process_stroke(
        session_factory=deps.session_factory,
        classifier=deps.classifier,
        pose_source=deps.pose_source,
        bat_source=deps.bat_source,
        ball_source=deps.ball_source,
        event_bus=deps.event_bus,
        tenant_id=envelope.tenant_id,
        correlation_id=envelope.correlation_id,
        person_id=_parse_person(p.get("person_id")),
        camera_angle=p.get("camera_angle"),
    )


def build_shot_consumer(deps: Deps, *, idempotency_store: IdempotencyStore) -> IdempotentConsumer:
    """Dedupe/retry/DLQ consumer over pose.keypoints -> shot runs."""

    async def _handler(envelope: EventEnvelope) -> None:
        await handle_pose_keypoints(deps, envelope)

    return IdempotentConsumer(
        bus=deps.event_bus,
        idempotency_store=idempotency_store,
        handler=_handler,
        source_topic=TOPIC_POSE_KEYPOINTS,
        dlq_topic=TOPIC_SHOT_DLQ,
        group_id=CONSUMER_GROUP,
    )
