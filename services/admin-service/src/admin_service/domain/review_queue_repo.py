"""M20's own biomechanics review queue (schema from Step 1; workflow, Step 6, FR-M20-06).

Global, no RLS — an admin's review queue spans every tenant by design, same
as the rest of the admin ops schema.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PENDING: Final[str] = "pending"
RESOLVED: Final[str] = "resolved"

_COLUMNS = (
    "id, tenant_id, stroke_ref, reason, status, reviewer, resolution_note, resolved_at, created_at"
)


async def upsert_pending(
    session: AsyncSession, *, tenant_id: uuid.UUID, stroke_ref: str, reason: str
) -> dict[str, Any]:
    """Add a flagged stroke to the queue. A no-op if it's already there
    (pending or resolved) — the same stroke is never flagged twice."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO review_queue (id, tenant_id, stroke_ref, reason) "
                    "VALUES (:id, :tid, :stroke, :reason) "
                    "ON CONFLICT (tenant_id, stroke_ref) "
                    "DO UPDATE SET tenant_id = EXCLUDED.tenant_id "
                    f"RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "stroke": stroke_ref, "reason": reason},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_items(
    session: AsyncSession, *, status: str = PENDING, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    query = (
        f"SELECT {_COLUMNS} FROM review_queue "  # nosec B608 -- _COLUMNS is a constant
        "WHERE status = :status ORDER BY created_at LIMIT :limit OFFSET :offset"
    )
    rows = (
        (await session.execute(text(query), {"status": status, "limit": limit, "offset": offset}))
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_item(session: AsyncSession, item_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM review_queue WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": item_id})).mappings().first()
    return dict(row) if row else None


async def resolve_item(
    session: AsyncSession, *, item_id: uuid.UUID, reviewer: str, resolution_note: str | None
) -> dict[str, Any] | None:
    """Resolve a PENDING item. Returns None if not found or already resolved."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE review_queue "
                    "SET status = 'resolved', reviewer = :reviewer, resolution_note = :note, "
                    "    resolved_at = now(), updated_at = now() "
                    "WHERE id = :id AND status = 'pending' "
                    f"RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {"reviewer": reviewer, "note": resolution_note, "id": item_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
