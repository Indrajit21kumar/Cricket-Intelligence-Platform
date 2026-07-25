"""Consent-gated annotation queue (shared by M07 and M08).

Extracted from bat-service when M08 began routing to the same queue. The move
was not tidying: the consent gate here is what keeps a child's frames out of a
training corpus, and a rule that important must exist once, audited, rather than
once per vision module.

The structure that makes it hard to misuse:

- **Selection and admission are separate.** Callers decide which frames are
  worth labelling and pass them in; this module decides whether they are
  ALLOWED. "Useful" can never quietly become "permitted".
- **Admission asks cip-core.** :func:`cip_core.may_use_for_training` is the one
  implementation of the policy — training consent, and for a minor, consent
  granted by a verified guardian.
- **Every row records why it was admitted.** ``consent_reason`` is written at
  admission, so an audit years later does not have to re-derive consent state
  that may since have changed.
- **Withdrawal is first class.** :func:`purge_person` exists because consent
  that cannot be revoked is not consent.

``modality`` distinguishes bat frames from ball frames of the same clip. They
are different training items — a labeller marking a bat is not marking a ball —
so the uniqueness key includes it, and one clip can legitimately appear twice.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import may_use_for_training

#: What kind of thing a queued frame is labelled for.
MODALITY_BAT = "bat"
MODALITY_BALL = "ball"
#: A whole-stroke shot label, not a per-frame geometry — the item is still a
#: frame range keyed by correlation_id, but the labeller assigns a shot class.
MODALITY_SHOT = "shot"

# Why a frame was selected. Shared vocabulary so the queue is queryable across
# modalities ("show me everything the models were unsure about").
REASON_FAILED = "failed"
REASON_LOW_CONFIDENCE = "low_confidence"
REASON_SAMPLED = "sampled"
#: The model abstained — a near-miss a human should disambiguate.
REASON_ABSTAINED = "abstained"


@dataclass(frozen=True, slots=True)
class SelectedFrame:
    """A frame proposed for labelling, before any consent decision."""

    frame_index: int
    reason: str
    weak_label: dict[str, Any] | None = None


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
    modality: str,
) -> EnqueueResult:
    """Admit selected frames into the queue, but only with training consent.

    Returns without queuing anything when consent is absent — the whole clip is
    refused rather than partially admitted, since consent is a property of the
    player, not of individual frames (M07 AC-M07-07, M08 §12).
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
                "   weak_label, consent_reason, modality) "
                "VALUES (:id, :tid, :corr, :pid, :fi, :reason, cast(:wl as jsonb), :cr, :mod) "
                # Re-running a clip must not duplicate its frames. Modality is
                # part of the key: a bat frame and a ball frame from the same
                # clip are different training items.
                "ON CONFLICT (tenant_id, correlation_id, modality, frame_index) DO NOTHING "
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
                "mod": modality,
            },
        )
        if result.first() is not None:
            queued += 1
    return EnqueueResult(queued=queued, consent_reason=decision.reason, allowed=True)


async def purge_person(session: AsyncSession, *, person_id: uuid.UUID) -> int:
    """Remove every queued frame for a player, in every modality.

    Called when training consent is withdrawn. Deliberately not scoped by
    modality: a player withdrawing consent is withdrawing it from the whole
    corpus, not from one model's slice of it.
    """
    result = await session.execute(
        text("DELETE FROM annotation_queue WHERE person_id = :pid RETURNING id"),
        {"pid": person_id},
    )
    return len(result.all())


async def queue_size(
    session: AsyncSession,
    *,
    correlation_id: str | None = None,
    modality: str | None = None,
) -> int:
    """Count queued frames, optionally for one clip and/or modality."""
    # Enumerated literal statements rather than an assembled string: there is
    # no interpolation to audit, so no suppression comment to take on trust.
    base = "SELECT count(*) FROM annotation_queue"
    params: dict[str, Any] = {}
    if correlation_id is not None and modality is not None:
        query = f"{base} WHERE correlation_id = :corr AND modality = :mod"
        params = {"corr": correlation_id, "mod": modality}
    elif correlation_id is not None:
        query = f"{base} WHERE correlation_id = :corr"
        params = {"corr": correlation_id}
    elif modality is not None:
        query = f"{base} WHERE modality = :mod"
        params = {"mod": modality}
    else:
        query = base
    result = await session.execute(text(query), params)
    return int(result.scalar_one())
