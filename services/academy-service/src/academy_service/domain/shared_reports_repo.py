"""shared_reports repository (M18 Step 7, §9).

Tenant-scoped (RLS). One row per completed share — an append-only audit
trail of who shared what with whom, never updated or deleted.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SHARE_COLUMNS = "id, tenant_id, report_ref, shared_with, shared_by, shared_at"


async def insert_share(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    report_ref: str,
    shared_with: str,
    shared_by: uuid.UUID | None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO shared_reports "  # nosec B608 -- constant columns
                    "  (id, tenant_id, report_ref, shared_with, shared_by) "
                    "VALUES (:id, :tid, :report_ref, :shared_with, :shared_by) "
                    f"RETURNING {_SHARE_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "report_ref": report_ref,
                    "shared_with": shared_with,
                    "shared_by": shared_by,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_shares_for_report(
    session: AsyncSession, *, tenant_id: uuid.UUID, report_ref: str
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_SHARE_COLUMNS} FROM shared_reports "  # nosec B608 -- constant columns
                    "WHERE tenant_id = :tid AND report_ref = :report_ref "
                    "ORDER BY shared_at DESC"
                ),
                {"tid": tenant_id, "report_ref": report_ref},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
