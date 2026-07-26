"""biomechanics_reports repository (M10 Step 7).

Tenant-scoped (RLS) store, idempotent on ``(tenant_id, correlation_id)`` so a
re-delivered stroke updates one report rather than duplicating (NFR-M10-04).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, shot_type, shot_confidence, "
    "phase_boundaries, phase_method, metrics, quality, schema_version, "
    "out_of_expected_range, reviewed_by_human, provisional, computed_at"
)


async def upsert_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    shot_type: str | None,
    shot_confidence: float | None,
    phase_boundaries: dict[str, int],
    phase_method: str,
    metrics: dict[str, Any],
    quality: dict[str, Any],
    schema_version: str,
    out_of_expected_range: bool,
    provisional: bool,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id). Returns the row."""
    row = (
        (
            await session.execute(
                text(
                    # Every caller value is a bound parameter; only the
                    # module-level _COLUMNS constant is interpolated.
                    "INSERT INTO biomechanics_reports "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, shot_type, shot_confidence, "
                    "   phase_boundaries, phase_method, metrics, quality, schema_version, "
                    "   out_of_expected_range, provisional) "
                    "VALUES (:id, :tid, :corr, :pid, :st, :sc, cast(:pb as jsonb), :pm, "
                    "        cast(:m as jsonb), cast(:q as jsonb), :sv, :oor, :prov) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, shot_type = EXCLUDED.shot_type, "
                    "  shot_confidence = EXCLUDED.shot_confidence, "
                    "  phase_boundaries = EXCLUDED.phase_boundaries, "
                    "  phase_method = EXCLUDED.phase_method, metrics = EXCLUDED.metrics, "
                    "  quality = EXCLUDED.quality, schema_version = EXCLUDED.schema_version, "
                    "  out_of_expected_range = EXCLUDED.out_of_expected_range, "
                    "  provisional = EXCLUDED.provisional, updated_at = now() "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "st": shot_type,
                    "sc": shot_confidence,
                    "pb": json.dumps(phase_boundaries),
                    "pm": phase_method,
                    "m": json.dumps(metrics),
                    "q": json.dumps(quality),
                    "sv": schema_version,
                    "oor": out_of_expected_range,
                    "prov": provisional,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_report(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    # _COLUMNS is a constant; correlation_id is a bound parameter.
    query = f"SELECT {_COLUMNS} FROM biomechanics_reports WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
