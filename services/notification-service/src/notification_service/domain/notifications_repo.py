"""notifications repository (M19 Steps 5 + 6, §9).

Person-anchored, no RLS (Step 1 migration). :func:`create_if_new` is the
FR-M19-07/NFR-M19-02 idempotency anchor: ``ON CONFLICT (idempotency_key)
DO NOTHING`` means a re-delivered event that maps to the same (event,
recipient, channel) key inserts nothing and the ``RETURNING`` clause
yields no row — the caller can tell "already handled" apart from "just
created" without a separate SELECT-then-INSERT race.

:func:`mark_read` scopes its UPDATE to ``recipient_ref`` as well as
``id`` — a caller can never mark someone else's notification read by
guessing an id, the WHERE clause itself is the access control.
:func:`find_by_provider_ref` joins through ``delivery_attempts`` because
the provider only ever hands back its OWN message ref (Step 3's
``dispatch()`` return value), never our notification id.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NOTIFICATION_COLUMNS = (
    "id, recipient_ref, type, channel, status, event_ref, idempotency_key, read_at, created_at"
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


async def list_for_recipient(
    session: AsyncSession,
    *,
    recipient_ref: uuid.UUID,
    channel: str = "in_app",
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """A recipient's in-app inbox (§10's ``GET /v1/notifications``), newest first."""
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_NOTIFICATION_COLUMNS} FROM notifications "  # nosec B608 -- constant columns
                    "WHERE recipient_ref = :recipient AND channel = :channel "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {
                    "recipient": recipient_ref,
                    "channel": channel,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def mark_read(
    session: AsyncSession, *, notification_id: uuid.UUID, recipient_ref: uuid.UUID
) -> bool:
    """Mark one notification read, scoped to its own recipient.

    Idempotent: ``COALESCE`` means a second call on an already-read
    notification still matches (returns True) without moving the original
    read timestamp. Returns False (no-op, not an error) for an unknown id
    or one that belongs to someone else — the caller can't distinguish
    "doesn't exist" from "isn't yours" from the response, which is the
    point.
    """
    row = (
        await session.execute(
            text(
                "UPDATE notifications "  # nosec B608 -- constant columns
                "SET read_at = COALESCE(read_at, now()) "
                "WHERE id = :id AND recipient_ref = :recipient "
                "RETURNING id"
            ),
            {"id": notification_id, "recipient": recipient_ref},
        )
    ).first()
    return row is not None


#: Same as _NOTIFICATION_COLUMNS but table-qualified — needed once a query
#: joins delivery_attempts, since both tables have their own id/status.
_QUALIFIED_NOTIFICATION_COLUMNS = (
    "n.id, n.recipient_ref, n.type, n.channel, n.status, n.event_ref, "
    "n.idempotency_key, n.read_at, n.created_at"
)


async def find_by_provider_ref(
    session: AsyncSession, *, provider_ref: str
) -> dict[str, Any] | None:
    """The notification a channel provider's own message ref belongs to.

    Joins through ``delivery_attempts`` — the provider only ever hands
    back its OWN ref (Step 3's dispatch() return value), never our
    notification id.
    """
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {_QUALIFIED_NOTIFICATION_COLUMNS} "  # nosec B608 -- constant columns
                    "FROM notifications n "
                    "JOIN delivery_attempts a ON a.notification_id = n.id "
                    "WHERE a.provider_ref = :provider_ref "
                    "ORDER BY a.attempt DESC LIMIT 1"
                ),
                {"provider_ref": provider_ref},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
