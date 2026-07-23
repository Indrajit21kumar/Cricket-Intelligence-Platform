"""Quality-flags repository (M05 Step 6).

Tenant-scoped record of the gate's decisions for a clip. Reprocessing a
re-delivered clip replaces the prior flags (delete + insert) so the stored
result always reflects the latest run (NFR-M05-05).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from video_service.domain.quality_gate import GateFlag


async def replace_flags(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    ingestion_id: uuid.UUID,
    flags: Iterable[GateFlag],
) -> None:
    """Replace all quality flags for an ingestion with ``flags``."""
    await session.execute(
        text("DELETE FROM quality_flags WHERE ingestion_id = :ing"),
        {"ing": ingestion_id},
    )
    for flag in flags:
        await session.execute(
            text(
                "INSERT INTO quality_flags "
                "  (id, tenant_id, ingestion_id, code, severity, message) "
                "VALUES (:id, :tid, :ing, :code, :sev, :msg)"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "ing": ingestion_id,
                "code": flag.code,
                "sev": flag.severity,
                "msg": flag.message,
            },
        )


async def get_flags(session: AsyncSession, ingestion_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT code, severity, message FROM quality_flags "
            "WHERE ingestion_id = :ing ORDER BY severity, code"
        ),
        {"ing": ingestion_id},
    )
    return [dict(r) for r in rows.mappings()]
