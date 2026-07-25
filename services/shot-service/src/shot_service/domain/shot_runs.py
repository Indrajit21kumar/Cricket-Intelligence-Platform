"""shot_runs repository (M09 Step 5).

Tenant-scoped (RLS) index of shot runs, idempotent on
``(tenant_id, correlation_id)`` so a re-delivered stroke updates one row rather
than duplicating (NFR-M09-03).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, model_version, dataset_version, "
    "shot_class, shot_confidence, phase_boundaries, phase_method, signals_used, "
    "quality, created_at"
)


async def upsert_shot_run(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    model_version: str,
    dataset_version: str | None,
    shot_class: str,
    shot_confidence: float,
    phase_boundaries: dict[str, int],
    phase_method: str,
    signals_used: list[str],
    quality: str,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id). Returns the row."""
    row = (
        (
            await session.execute(
                text(
                    # Every caller value is a bound parameter; only the
                    # module-level _COLUMNS constant is interpolated.
                    "INSERT INTO shot_runs "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, model_version, "
                    "   dataset_version, shot_class, shot_confidence, phase_boundaries, "
                    "   phase_method, signals_used, quality) "
                    "VALUES (:id, :tid, :corr, :pid, :mv, :dv, :sc, :conf, "
                    "        cast(:phases as jsonb), :pm, cast(:signals as jsonb), :q) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, model_version = EXCLUDED.model_version, "
                    "  dataset_version = EXCLUDED.dataset_version, "
                    "  shot_class = EXCLUDED.shot_class, "
                    "  shot_confidence = EXCLUDED.shot_confidence, "
                    "  phase_boundaries = EXCLUDED.phase_boundaries, "
                    "  phase_method = EXCLUDED.phase_method, "
                    "  signals_used = EXCLUDED.signals_used, quality = EXCLUDED.quality, "
                    "  updated_at = now() "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "mv": model_version,
                    "dv": dataset_version,
                    "sc": shot_class,
                    "conf": shot_confidence,
                    "phases": json.dumps(phase_boundaries),
                    "pm": phase_method,
                    "signals": json.dumps(signals_used),
                    "q": quality,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_shot_run(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    # _COLUMNS is a constant; correlation_id is a bound parameter.
    query = f"SELECT {_COLUMNS} FROM shot_runs WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
