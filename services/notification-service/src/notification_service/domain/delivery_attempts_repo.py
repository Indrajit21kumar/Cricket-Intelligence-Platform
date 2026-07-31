"""delivery_attempts repository (M19 Step 5, §9).

One row per attempt — an append-only trail, never updated. Cascades on
its parent ``notifications`` row's delete (Step 1 migration).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_ATTEMPT_COLUMNS = "id, notification_id, attempt, status, provider_ref, at"


async def record_attempt(
    session: AsyncSession,
    *,
    notification_id: uuid.UUID,
    attempt: int,
    status: str,
    provider_ref: str | None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO delivery_attempts "  # nosec B608 -- constant columns
                    "  (id, notification_id, attempt, status, provider_ref) "
                    "VALUES (:id, :nid, :attempt, :status, :provider_ref) "
                    f"RETURNING {_ATTEMPT_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "nid": notification_id,
                    "attempt": attempt,
                    "status": status,
                    "provider_ref": provider_ref,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def count_attempts(session: AsyncSession, *, notification_id: uuid.UUID) -> int:
    result = (
        await session.execute(
            text(
                "SELECT count(*) FROM delivery_attempts "  # nosec B608 -- constant columns
                "WHERE notification_id = :nid"
            ),
            {"nid": notification_id},
        )
    ).scalar_one()
    return int(result)


async def list_attempts(
    session: AsyncSession, *, notification_id: uuid.UUID
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_ATTEMPT_COLUMNS} FROM delivery_attempts "  # nosec B608 -- constant columns
                    "WHERE notification_id = :nid ORDER BY attempt"
                ),
                {"nid": notification_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
