"""Calibration repository (M05 Steps 4-5).

Tenant-scoped; one row per ingestion (the Book 4 Ch. 2 calibration envelope).
Step 4 writes ``camera_angle``; Step 5 fills ``pixel_to_meter``,
``spatial_confidence``, ``depth_estimated``, and ``method``. Idempotent on
``ingestion_id`` (NFR-M05-05).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def upsert_calibration(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ingestion_id: uuid.UUID,
    camera_angle: str,
    pixel_to_meter: float | None = None,
    spatial_confidence: str = "low",
    depth_estimated: bool = True,
    method: str | None = None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO calibrations "
                    "  (id, tenant_id, ingestion_id, pixel_to_meter, camera_angle, "
                    "   spatial_confidence, depth_estimated, method) "
                    "VALUES (:id, :tid, :ing, :ptm, :angle, :sc, :depth, :method) "
                    "ON CONFLICT (ingestion_id) DO UPDATE SET "
                    "  pixel_to_meter = EXCLUDED.pixel_to_meter, "
                    "  camera_angle = EXCLUDED.camera_angle, "
                    "  spatial_confidence = EXCLUDED.spatial_confidence, "
                    "  depth_estimated = EXCLUDED.depth_estimated, "
                    "  method = EXCLUDED.method, updated_at = now() "
                    "RETURNING id, ingestion_id, pixel_to_meter, camera_angle, "
                    "          spatial_confidence, depth_estimated, method"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "ing": ingestion_id,
                    "ptm": pixel_to_meter,
                    "angle": camera_angle,
                    "sc": spatial_confidence,
                    "depth": depth_estimated,
                    "method": method,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_calibration(session: AsyncSession, ingestion_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, ingestion_id, pixel_to_meter, camera_angle, "
                    "       spatial_confidence, depth_estimated, method "
                    "FROM calibrations WHERE ingestion_id = :ing"
                ),
                {"ing": ingestion_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
