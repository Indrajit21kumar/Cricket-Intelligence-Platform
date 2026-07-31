"""Tenant administration (M20 Step 3, FR-M20-01).

Reads/writes the shared, base-schema ``tenants`` table directly — the same
table every service's own tests already create tenants in via
``admin_session``. No RLS: a tenant registry row belongs to the platform,
not to any one tenant's row-level scope.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ACTIVE: Final[str] = "active"
SUSPENDED: Final[str] = "suspended"
ADMIN_SETTABLE_STATUSES: Final[tuple[str, ...]] = (ACTIVE, SUSPENDED)

_COLUMNS = "id, name, type, region, status, created_at"


async def get_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM tenants WHERE id = :id"  # nosec B608 -- _COLUMNS is a constant
    row = (await session.execute(text(query), {"id": tenant_id})).mappings().first()
    return dict(row) if row else None


async def set_tenant_status(
    session: AsyncSession, tenant_id: uuid.UUID, new_status: str
) -> dict[str, Any] | None:
    """Suspend or restore a tenant. Returns the updated row, or None if not found."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE tenants SET status = :s, updated_at = now() "
                    f"WHERE id = :id RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {"s": new_status, "id": tenant_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
