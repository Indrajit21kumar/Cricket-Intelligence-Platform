"""notifications repository (M19 Step 5, §9).

Person-anchored, no RLS (Step 1 migration). :func:`create_if_new` is the
FR-M19-07/NFR-M19-02 idempotency anchor: ``ON CONFLICT (idempotency_key)
DO NOTHING`` means a re-delivered event that maps to the same (event,
recipient, channel) key inserts nothing and the ``RETURNING`` clause
yields no row — the caller can tell "already handled" apart from "just
created" without a separate SELECT-then-INSERT race.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NOTIFICATION_COLUMNS = (
    "id, recipient_ref, type, channel, status, event_ref, idempotency_key, created_at"
)


async def create_if_new(
    session: AsyncSession,
    *,
    recipient_ref: uuid.UUID,
    notification_type: str,
    channel: str,
    event_ref: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    """Insert a new notification row, or None if this idempotency_key already exists."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO notifications "  # nosec B608 -- constant columns
                    "  (id, recipient_ref, type, channel, event_ref, idempotency_key) "
                    "VALUES (:id, :recipient, :type, :channel, :event_ref, :key) "
                    "ON CONFLICT (idempotency_key) DO NOTHING "
                    f"RETURNING {_NOTIFICATION_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "recipient": recipient_ref,
                    "type": notification_type,
                    "channel": channel,
                    "event_ref": event_ref,
                    "key": idempotency_key,
                },
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def update_status(session: AsyncSession, *, notification_id: uuid.UUID, status: str) -> None:
    await session.execute(
        text("UPDATE notifications SET status = :status WHERE id = :id"),
        {"id": notification_id, "status": status},
    )


async def get_by_idempotency_key(
    session: AsyncSession, *, idempotency_key: str
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {_NOTIFICATION_COLUMNS} FROM notifications "  # nosec B608 -- constant columns
                    "WHERE idempotency_key = :key"
                ),
                {"key": idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
