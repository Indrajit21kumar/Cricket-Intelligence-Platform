"""ball_runs repository (M08 Step 7).

Tenant-scoped (RLS) index of ball runs, idempotent on
``(tenant_id, correlation_id)`` so a re-delivered clip updates one row rather
than duplicating (NFR-M08-04).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, model_version, dataset_version, "
    "frame_count, frames_detected, track_confidence, timing_reference, "
    "conditions_met, events, quality, artefact_ref, created_at"
)


async def upsert_ball_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    model_version: str,
    dataset_version: str | None,
    frame_count: int,
    frames_detected: int,
    track_confidence: float,
    timing_reference: str,
    conditions_met: bool,
    events: dict[str, Any],
    quality: str,
    artefact_ref: str | None,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id). Returns the row."""
    row = (
        (
            await session.execute(
                text(
                    # Every caller value is a bound parameter; only the
                    # module-level _COLUMNS constant is interpolated.
                    "INSERT INTO ball_runs "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, model_version, "
                    "   dataset_version, frame_count, frames_detected, track_confidence, "
                    "   timing_reference, conditions_met, events, quality, artefact_ref) "
                    "VALUES (:id, :tid, :corr, :pid, :mv, :dv, :fc, :fd, :tc, :tr, :cm, "
                    "        cast(:events as jsonb), :q, :ar) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, model_version = EXCLUDED.model_version, "
                    "  dataset_version = EXCLUDED.dataset_version, "
                    "  frame_count = EXCLUDED.frame_count, "
                    "  frames_detected = EXCLUDED.frames_detected, "
                    "  track_confidence = EXCLUDED.track_confidence, "
                    "  timing_reference = EXCLUDED.timing_reference, "
                    "  conditions_met = EXCLUDED.conditions_met, "
                    "  events = EXCLUDED.events, quality = EXCLUDED.quality, "
                    "  artefact_ref = EXCLUDED.artefact_ref, updated_at = now() "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "mv": model_version,
                    "dv": dataset_version,
                    "fc": frame_count,
                    "fd": frames_detected,
                    "tc": track_confidence,
                    "tr": timing_reference,
                    "cm": conditions_met,
                    "events": json.dumps(events),
                    "q": quality,
                    "ar": artefact_ref,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_ball_run(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    # _COLUMNS is a constant; correlation_id is a bound parameter.
    query = f"SELECT {_COLUMNS} FROM ball_runs WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
