"""Processing-results repository (M05 Step 3).

Tenant-scoped; one row per ingestion (the normalised clip's media metadata).
Idempotent on ``ingestion_id`` so re-processing a re-delivered clip updates
the same row rather than duplicating (NFR-M05-05).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def save_processing_result(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ingestion_id: uuid.UUID,
    normalized_ref: str,
    frame_count: int,
    fps: float,
    width: int,
    height: int,
    duration_s: float,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO processing_results "
                    "  (id, tenant_id, ingestion_id, normalized_ref, frame_count, "
                    "   fps, width, height, duration_s) "
                    "VALUES (:id, :tid, :ing, :nref, :fc, :fps, :w, :h, :dur) "
                    "ON CONFLICT (ingestion_id) DO UPDATE SET "
                    "  normalized_ref = EXCLUDED.normalized_ref, "
                    "  frame_count = EXCLUDED.frame_count, fps = EXCLUDED.fps, "
                    "  width = EXCLUDED.width, height = EXCLUDED.height, "
                    "  duration_s = EXCLUDED.duration_s, updated_at = now() "
                    "RETURNING id, ingestion_id, normalized_ref, frame_count, fps, "
                    "          width, height, duration_s"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "ing": ingestion_id,
                    "nref": normalized_ref,
                    "fc": frame_count,
                    "fps": fps,
                    "w": width,
                    "h": height,
                    "dur": duration_s,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_processing_result(
    session: AsyncSession, ingestion_id: uuid.UUID
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, ingestion_id, normalized_ref, frame_count, fps, "
                    "       width, height, duration_s "
                    "FROM processing_results WHERE ingestion_id = :ing"
                ),
                {"ing": ingestion_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
