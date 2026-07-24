"""Annotation pipeline — the consent-gated training-data flywheel (M07 Step 2).

The loop: a run finishes → frames worth labelling are *selected* → each is
admitted only if that player consented to training use → labelled by humans →
frozen into a versioned corpus → a detector trained on that version records it
in ``bat_runs.dataset_version``.

The consent gate is the part that matters most and the part easiest to get
quietly wrong, so it is structured to fail closed:

- selection and admission are separate functions, so "which frames are useful"
  can never accidentally become "which frames are allowed";
- admission asks :func:`cip_core.may_use_for_training`, the one audited
  implementation, rather than re-reading consent tables here;
- the granting decision is written onto the row (``consent_reason``), so the
  queue carries its own justification;
- withdrawal is a first-class operation (:func:`purge_person`), because
  consent that cannot be revoked is not consent.

What this step does NOT deliver: an actual labelled cricket-bat corpus. That
needs real clips, real consent and human labellers. What exists here is the
mechanism that produces one safely.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bat_service.domain.bat import BatFrame
from cip_core import may_use_for_training
from cip_data import admin_session, tenant_session

# Why a frame was selected for labelling.
REASON_FAILED = "failed"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_SAMPLED = "sampled"

#: Frames the detector was unsure about are the most informative to label.
LOW_CONFIDENCE_THRESHOLD = 0.6
#: Take every Nth confident frame too, so the corpus keeps easy cases and does
#: not drift into being only hard ones.
SAMPLE_EVERY = 10


@dataclass(frozen=True, slots=True)
class SelectedFrame:
    """A frame proposed for labelling, before any consent decision."""

    frame_index: int
    reason: str
    weak_label: dict[str, Any] | None = None


def select_frames(
    frames: tuple[BatFrame, ...],
    *,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    sample_every: int = SAMPLE_EVERY,
) -> tuple[SelectedFrame, ...]:
    """Choose which frames are worth a human's time. No consent logic here."""
    selected: list[SelectedFrame] = []
    for frame in frames:
        if not frame.detected:
            selected.append(SelectedFrame(frame_index=frame.frame_index, reason=REASON_FAILED))
            continue
        weak_label = {
            "parts": [
                {"part": p.part, "x": p.x, "y": p.y, "confidence": p.confidence}
                for p in frame.parts
            ]
        }
        if frame.confidence < low_confidence_threshold:
            selected.append(
                SelectedFrame(
                    frame_index=frame.frame_index,
                    reason=REASON_LOW_CONFIDENCE,
                    weak_label=weak_label,
                )
            )
        elif sample_every > 0 and frame.frame_index % sample_every == 0:
            selected.append(
                SelectedFrame(
                    frame_index=frame.frame_index,
                    reason=REASON_SAMPLED,
                    weak_label=weak_label,
                )
            )
    return tuple(selected)


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """What admission did, and why — the caller logs this."""

    queued: int
    #: training_consent | guardian_consent when admitted; the denial reason
    #: (no_training_consent | minor_requires_guardian_consent | unknown_person)
    #: when nothing was queued.
    consent_reason: str
    allowed: bool


async def enqueue_frames(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    frames: tuple[SelectedFrame, ...],
) -> EnqueueResult:
    """Admit selected frames into the queue, but only with training consent.

    Returns without queuing anything when consent is absent — the whole clip
    is refused rather than partially admitted, since consent is a property of
    the player, not of individual frames (AC-M07-07).
    """
    if person_id is None:
        # No identified player means no one could have consented.
        return EnqueueResult(queued=0, consent_reason="unknown_person", allowed=False)

    decision = await may_use_for_training(session, person_id=person_id, tenant_id=tenant_id)
    if not decision.allowed:
        return EnqueueResult(queued=0, consent_reason=decision.reason, allowed=False)

    queued = 0
    for frame in frames:
        result = await session.execute(
            text(
                "INSERT INTO annotation_queue "
                "  (id, tenant_id, correlation_id, person_id, frame_index, reason, "
                "   weak_label, consent_reason) "
                "VALUES (:id, :tid, :corr, :pid, :fi, :reason, cast(:wl as jsonb), :cr) "
                # Re-running a clip must not duplicate its frames.
                "ON CONFLICT (tenant_id, correlation_id, frame_index) DO NOTHING "
                "RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "corr": correlation_id,
                "pid": person_id,
                "fi": frame.frame_index,
                "reason": frame.reason,
                "wl": json.dumps(frame.weak_label) if frame.weak_label else None,
                "cr": decision.reason,
            },
        )
        if result.first() is not None:
            queued += 1
    return EnqueueResult(queued=queued, consent_reason=decision.reason, allowed=True)


async def purge_person(session: AsyncSession, *, person_id: uuid.UUID) -> int:
    """Remove every queued frame for a player. Returns the number removed.

    Called when training consent is withdrawn. Frames already frozen into a
    released dataset are removed from the queue too; the corpus itself is
    re-cut from the queue, so the next freeze no longer contains them.
    """
    result = await session.execute(
        text("DELETE FROM annotation_queue WHERE person_id = :pid RETURNING id"),
        {"pid": person_id},
    )
    return len(result.all())


async def queue_size(session: AsyncSession, *, correlation_id: str | None = None) -> int:
    """Count queued frames (optionally for one clip). RLS scopes it to tenant."""
    if correlation_id is None:
        result = await session.execute(text("SELECT count(*) FROM annotation_queue"))
    else:
        result = await session.execute(
            text("SELECT count(*) FROM annotation_queue WHERE correlation_id = :corr"),
            {"corr": correlation_id},
        )
    return int(result.scalar_one())


def dataset_checksum(items: list[tuple[str, int]]) -> str:
    """Stable hash over (correlation_id, frame_index) pairs, order-independent."""
    joined = "|".join(f"{corr}:{idx}" for corr, idx in sorted(items))
    return hashlib.sha256(joined.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    version: str
    item_count: int
    checksum: str


async def freeze_dataset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    version: str,
    tenant_ids: Sequence[uuid.UUID],
    notes: str | None = None,
) -> DatasetVersion:
    """Freeze the unassigned queued frames of the given tenants into a corpus.

    Freezing is what makes a detector reproducible: ``bat_runs.dataset_version``
    plus this checksum answers "exactly which frames did this model learn
    from?" — the traceability ENG-007's gate depends on.

    ``tenant_ids`` is explicit rather than implied, for a structural reason.
    The queue is tenant-scoped under RLS and ``admin_session`` deliberately
    sees NOTHING through that policy, so there is no ambient "every row" view
    to freeze from — and there should not be. A training corpus aggregates
    many academies' players, so the tenants it draws from are named by the
    operator and visible at the call site, rather than a cross-tenant sweep
    happening quietly.
    """
    items: list[tuple[str, int]] = []
    for tenant_id in tenant_ids:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT correlation_id, frame_index FROM annotation_queue "
                        "WHERE dataset_version IS NULL ORDER BY correlation_id, frame_index"
                    )
                )
            ).all()
            items.extend((str(r[0]), int(r[1])) for r in rows)
            await session.execute(
                text(
                    "UPDATE annotation_queue SET dataset_version = :v WHERE dataset_version IS NULL"
                ),
                {"v": version},
            )

    checksum = dataset_checksum(items)
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO annotation_datasets (id, version, item_count, checksum, notes) "
                "VALUES (:id, :v, :n, :c, :notes)"
            ),
            {
                "id": uuid.uuid4(),
                "v": version,
                "n": len(items),
                "c": checksum,
                "notes": notes,
            },
        )
    return DatasetVersion(version=version, item_count=len(items), checksum=checksum)


async def get_dataset(session: AsyncSession, version: str) -> DatasetVersion | None:
    row = (
        await session.execute(
            text(
                "SELECT version, item_count, checksum FROM annotation_datasets WHERE version = :v"
            ),
            {"v": version},
        )
    ).first()
    if row is None:
        return None
    return DatasetVersion(version=row[0], item_count=int(row[1]), checksum=row[2])
