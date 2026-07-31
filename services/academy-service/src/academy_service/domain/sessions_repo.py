"""academy_sessions / session_players repository (M18 Step 7, §9).

Tenant-scoped (RLS). Status transitions are validated by
:mod:`academy_service.domain.session` before this repo is ever asked to
write one — this module trusts the caller and just persists.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SESSION_COLUMNS = "id, tenant_id, coach_ref, scheduled_at, status, created_at, updated_at"
_ATTENDANCE_COLUMNS = "id, tenant_id, session_id, player_ref, attended, analysis_ref, created_at"


async def create_session(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    coach_ref: uuid.UUID | None,
    scheduled_at: Any,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO academy_sessions "  # nosec B608 -- constant columns
                    "  (id, tenant_id, coach_ref, scheduled_at) "
                    "VALUES (:id, :tid, :coach, :scheduled_at) "
                    f"RETURNING {_SESSION_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "coach": coach_ref,
                    "scheduled_at": scheduled_at,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_session(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {_SESSION_COLUMNS} FROM academy_sessions "  # nosec B608 -- constant columns
                    "WHERE tenant_id = :tid AND id = :id"
                ),
                {"tid": tenant_id, "id": session_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def update_session_status(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID, status: str
) -> None:
    await session.execute(
        text(
            "UPDATE academy_sessions SET status = :status, updated_at = now() "
            "WHERE tenant_id = :tid AND id = :id"
        ),
        {"tid": tenant_id, "id": session_id, "status": status},
    )


async def record_attendance(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    player_ref: uuid.UUID,
    attended: bool,
    analysis_ref: str | None,
) -> dict[str, Any]:
    """Upsert one player's attendance for a session (idempotent per player)."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO session_players "  # nosec B608 -- constant columns
                    "  (id, tenant_id, session_id, player_ref, attended, analysis_ref) "
                    "VALUES (:id, :tid, :sid, :player, :attended, :analysis_ref) "
                    "ON CONFLICT (session_id, player_ref) "
                    "DO UPDATE SET attended = :attended, analysis_ref = :analysis_ref "
                    f"RETURNING {_ATTENDANCE_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "sid": session_id,
                    "player": player_ref,
                    "attended": attended,
                    "analysis_ref": analysis_ref,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_attendance(
    session: AsyncSession, *, tenant_id: uuid.UUID, session_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_ATTENDANCE_COLUMNS} FROM session_players "  # nosec B608 -- constant columns
                    "WHERE tenant_id = :tid AND session_id = :sid"
                ),
                {"tid": tenant_id, "sid": session_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
