"""reasoning_results + finding_evidence repository (M13 Step 8).

Tenant-scoped (RLS) store, idempotent on ``(tenant_id, correlation_id)`` so a
re-delivered stroke updates one row rather than duplicating (NFR-M13-03).
Every re-persist rewrites the ``finding_evidence`` rows too, so the reverse-
lookup index stays true to the current result.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_RESULT_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, shot_type, shot_confidence, kg_version, "
    "findings, match_risk, quality, schema_version, provisional, computed_at"
)


async def upsert_result(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    shot_type: str | None,
    shot_confidence: float | None,
    kg_version: str,
    findings: list[dict[str, Any]],
    match_risk: dict[str, Any],
    quality: dict[str, Any],
    schema_version: str,
    provisional: bool,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id)."""
    row = (
        (
            await session.execute(
                text(
                    # Only the module-level _RESULT_COLUMNS constant is interpolated.
                    "INSERT INTO reasoning_results "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, shot_type, shot_confidence, "
                    "   kg_version, findings, match_risk, quality, schema_version, provisional) "
                    "VALUES (:id, :tid, :corr, :pid, :st, :sc, :kgv, cast(:f as jsonb), "
                    "        cast(:mr as jsonb), cast(:q as jsonb), :sv, :prov) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, shot_type = EXCLUDED.shot_type, "
                    "  shot_confidence = EXCLUDED.shot_confidence, "
                    "  kg_version = EXCLUDED.kg_version, findings = EXCLUDED.findings, "
                    "  match_risk = EXCLUDED.match_risk, quality = EXCLUDED.quality, "
                    "  schema_version = EXCLUDED.schema_version, "
                    "  provisional = EXCLUDED.provisional, updated_at = now() "
                    f"RETURNING {_RESULT_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "st": shot_type,
                    "sc": shot_confidence,
                    "kgv": kg_version,
                    "f": json.dumps(findings),
                    "mr": json.dumps(match_risk),
                    "q": json.dumps(quality),
                    "sv": schema_version,
                    "prov": provisional,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def replace_evidence(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    result_id: uuid.UUID,
    evidence_rows: list[dict[str, Any]],
) -> None:
    """Rewrite finding_evidence for a result: delete old rows, insert new ones."""
    await session.execute(
        text("DELETE FROM finding_evidence WHERE result_id = :rid"), {"rid": result_id}
    )
    if not evidence_rows:
        return
    await session.execute(
        text(
            "INSERT INTO finding_evidence "
            "  (id, tenant_id, result_id, finding_ref, metric_ids, rule_id, rule_version) "
            "VALUES (:id, :tid, :rid, :fref, cast(:mids as jsonb), :rule_id, :rule_version)"
        ),
        [
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "rid": result_id,
                "fref": row["finding_ref"],
                "mids": json.dumps(row["metric_ids"]),
                "rule_id": row["rule_id"],
                "rule_version": row["rule_version"],
            }
            for row in evidence_rows
        ],
    )


async def get_result(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    query = f"SELECT {_RESULT_COLUMNS} FROM reasoning_results WHERE correlation_id = :corr"  # nosec B608 -- constant columns
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None
