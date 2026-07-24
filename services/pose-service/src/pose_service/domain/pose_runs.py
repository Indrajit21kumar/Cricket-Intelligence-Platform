"""pose_runs repository (M06 Step 6).

Tenant-scoped (RLS) index of pose runs. The upsert is idempotent on
``(tenant_id, correlation_id)`` so a re-delivered clip updates the same row
rather than duplicating (NFR-M06-04).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, model_version, frame_count, "
    "mean_confidence, subject_status, quality, artefact_ref, depth_estimated, created_at"
)


async def upsert_pose_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    model_version: str,
    frame_count: int,
    mean_confidence: float | None,
    subject_status: str,
    quality: str,
    artefact_ref: str | None,
    depth_estimated: bool,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id). Returns the row."""
    row = (
        (
            await session.execute(
                text(
                    # Every caller value below is a bound parameter; the only
                    # interpolation is the module-level _COLUMNS constant.
                    "INSERT INTO pose_runs "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, model_version, "
                    "   frame_count, mean_confidence, subject_status, quality, "
                    "   artefact_ref, depth_estimated) "
                    "VALUES (:id, :tid, :corr, :pid, :mv, :fc, :mc, :ss, :q, :ar, :de) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, model_version = EXCLUDED.model_version, "
                    "  frame_count = EXCLUDED.frame_count, "
                    "  mean_confidence = EXCLUDED.mean_confidence, "
                    "  subject_status = EXCLUDED.subject_status, quality = EXCLUDED.quality, "
                    "  artefact_ref = EXCLUDED.artefact_ref, "
                    "  depth_estimated = EXCLUDED.depth_estimated, updated_at = now() "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "mv": model_version,
                    "fc": frame_count,
                    "mc": mean_confidence,
                    "ss": subject_status,
                    "q": quality,
                    "ar": artefact_ref,
                    "de": depth_estimated,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_pose_run(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    # _COLUMNS is a constant; correlation_id is a bound parameter.
    query = f"SELECT {_COLUMNS} FROM pose_runs WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
