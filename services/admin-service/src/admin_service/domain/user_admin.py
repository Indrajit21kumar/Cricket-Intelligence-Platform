"""User administration (M20 Step 3, FR-M20-01).

Reads/writes M02's ``persons`` table directly — the same precedent
``cip_core.consent`` already set for identity-adjacent reads from outside
identity-service itself. Only ``active``/``suspended`` are toggled here;
consent, verification, and deletion states stay M02's own domain and are
never touched by a support action.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ACTIVE: Final[str] = "active"
SUSPENDED: Final[str] = "suspended"
#: The only states an admin support action may move a person into.
ADMIN_SETTABLE_STATUSES: Final[tuple[str, ...]] = (ACTIVE, SUSPENDED)

_COLUMNS = "id, email, status, dob_band, display_name, created_at"


async def search_users(
    session: AsyncSession, *, query: str | None, limit: int = 50, offset: int = 0
) -> list[dict[str, Any]]:
    """Search persons by email/display name substring (case-insensitive)."""
    sql = f"SELECT {_COLUMNS} FROM persons "  # nosec B608 -- _COLUMNS is a constant
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if query:
        sql += "WHERE email ILIKE :q OR display_name ILIKE :q "
        params["q"] = f"%{query}%"
    sql += "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
    rows = (await session.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


async def get_user(session: AsyncSession, person_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM persons WHERE id = :id"  # nosec B608 -- _COLUMNS is a constant
    row = (await session.execute(text(query), {"id": person_id})).mappings().first()
    return dict(row) if row else None


async def set_user_status(
    session: AsyncSession, person_id: uuid.UUID, new_status: str
) -> dict[str, Any] | None:
    """Suspend or restore a person. Returns the updated row, or None if not found."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE persons SET status = :s, updated_at = now() "
                    f"WHERE id = :id RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {"s": new_status, "id": person_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
