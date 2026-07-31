"""coach_assignments repository (M18 Step 7, §9).

Tenant-scoped (RLS). Assignment is append-only-active: :func:`assign`
upserts on the ``(tenant_id, coach_ref, player_ref)`` unique pair rather
than inserting a duplicate row, and :func:`deactivate` flips ``active``
false rather than deleting — the historical record of who coached whom
survives (Step 1's migration docstring), and portability is enforced
independently at read time (:mod:`academy_service.domain.access`), never
by mutating this table.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ASSIGNMENT_COLUMNS = "id, tenant_id, coach_ref, player_ref, active, created_at, updated_at"


async def assign(
    session: AsyncSession, *, tenant_id: uuid.UUID, coach_ref: uuid.UUID, player_ref: uuid.UUID
) -> dict[str, Any]:
    """Create or reactivate the (coach, player) assignment; idempotent."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO coach_assignments "  # nosec B608 -- constant columns
                    "  (id, tenant_id, coach_ref, player_ref) "
                    "VALUES (:id, :tid, :coach, :player) "
                    "ON CONFLICT (tenant_id, coach_ref, player_ref) "
                    "DO UPDATE SET active = true, updated_at = now() "
                    f"RETURNING {_ASSIGNMENT_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "coach": coach_ref,
                    "player": player_ref,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def deactivate(
    session: AsyncSession, *, tenant_id: uuid.UUID, coach_ref: uuid.UUID, player_ref: uuid.UUID
) -> None:
    await session.execute(
        text(
            "UPDATE coach_assignments SET active = false, updated_at = now() "
            "WHERE tenant_id = :tid AND coach_ref = :coach AND player_ref = :player"
        ),
        {"tid": tenant_id, "coach": coach_ref, "player": player_ref},
    )


async def is_assigned(
    session: AsyncSession, *, tenant_id: uuid.UUID, coach_ref: uuid.UUID, player_ref: uuid.UUID
) -> bool:
    """Whether this coach currently has an ACTIVE assignment to this player."""
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM coach_assignments "  # nosec B608 -- constant columns
                "WHERE tenant_id = :tid AND coach_ref = :coach AND player_ref = :player "
                "  AND active LIMIT 1"
            ),
            {"tid": tenant_id, "coach": coach_ref, "player": player_ref},
        )
    ).first()
    return row is not None


async def active_assignments_by_player(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Every active assignment in this tenant, player_ref -> [coach_ref, ...]."""
    rows = (
        await session.execute(
            text(
                "SELECT player_ref, coach_ref FROM coach_assignments "  # nosec B608 -- constant columns
                "WHERE tenant_id = :tid AND active"
            ),
            {"tid": tenant_id},
        )
    ).all()
    result: dict[uuid.UUID, list[uuid.UUID]] = {}
    for player_ref, coach_ref in rows:
        result.setdefault(player_ref, []).append(coach_ref)
    return result
