"""Content moderation (M20 Step 3, FR-M20-02).

``moderation_cases`` is global (no RLS, same as the rest of the admin ops
schema) — an admin's moderation queue spans every tenant by design.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

OPEN: Final[str] = "open"
ACTIONED: Final[str] = "actioned"
DISMISSED: Final[str] = "dismissed"
#: The only decisions :func:`resolve_case` may record.
RESOLUTION_DECISIONS: Final[tuple[str, ...]] = (ACTIONED, DISMISSED)

_COLUMNS = (
    "id, tenant_id, subject_ref, reason, status, action, actioned_by, actioned_at, created_at"
)


async def create_case(
    session: AsyncSession, *, subject_ref: str, reason: str, tenant_id: uuid.UUID | None = None
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO moderation_cases (id, tenant_id, subject_ref, reason) "
                    f"VALUES (:id, :tid, :subject, :reason) RETURNING {_COLUMNS}"  # nosec B608
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "subject": subject_ref, "reason": reason},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_cases(
    session: AsyncSession, *, status: str = OPEN, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    query = (
        f"SELECT {_COLUMNS} FROM moderation_cases "  # nosec B608 -- _COLUMNS is a constant
        "WHERE status = :status ORDER BY created_at LIMIT :limit OFFSET :offset"
    )
    rows = (
        (await session.execute(text(query), {"status": status, "limit": limit, "offset": offset}))
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_case(session: AsyncSession, case_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM moderation_cases WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": case_id})).mappings().first()
    return dict(row) if row else None


async def resolve_case(
    session: AsyncSession,
    *,
    case_id: uuid.UUID,
    decision: str,
    actioned_by: str,
    action_taken: str | None = None,
) -> dict[str, Any] | None:
    """Resolve an OPEN case as actioned or dismissed. Returns None if not open."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE moderation_cases "
                    "SET status = :decision, action = :action, actioned_by = :by, "
                    "    actioned_at = now(), updated_at = now() "
                    "WHERE id = :id AND status = 'open' "
                    f"RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {"decision": decision, "action": action_taken, "by": actioned_by, "id": case_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
