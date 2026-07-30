"""comparisons repository (M15 Step 7, §9).

Tenant-scoped (RLS) store, idempotent on ``(tenant_id, correlation_id)`` so a
re-delivered stroke updates one row rather than duplicating (NFR-M15-03).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, per_metric, legend_similarity, "
    "benchmark_version, confidence, schema_version, provisional, computed_at, updated_at"
)


async def upsert_comparison(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    per_metric: list[dict[str, Any]],
    legend_similarity: dict[str, Any] | None,
    benchmark_version: str,
    confidence: float | None,
    schema_version: str,
    provisional: bool,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id)."""
    row = (
        (
            await session.execute(
                text(
                    # Only the module-level _COLUMNS constant is interpolated.
                    "INSERT INTO comparisons "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, per_metric, "
                    "   legend_similarity, benchmark_version, confidence, schema_version, "
                    "   provisional) "
                    "VALUES (:id, :tid, :corr, :pid, cast(:pm as jsonb), "
                    "        cast(:ls as jsonb), :bv, :conf, :sv, :prov) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, per_metric = EXCLUDED.per_metric, "
                    "  legend_similarity = EXCLUDED.legend_similarity, "
                    "  benchmark_version = EXCLUDED.benchmark_version, "
                    "  confidence = EXCLUDED.confidence, "
                    "  schema_version = EXCLUDED.schema_version, "
                    "  provisional = EXCLUDED.provisional, updated_at = now() "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "pm": json.dumps(per_metric),
                    "ls": json.dumps(legend_similarity) if legend_similarity is not None else "{}",
                    "bv": benchmark_version,
                    "conf": confidence,
                    "sv": schema_version,
                    "prov": provisional,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_comparison(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM comparisons WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
