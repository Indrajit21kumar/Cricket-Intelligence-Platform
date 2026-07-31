"""preferences repository (M19 Step 4, §9).

Person-anchored, no RLS (see the Step 1 migration docstring); all access
via ``admin_session``. Upserts on the ``(person_ref, channel, topic)``
unique triple — a preference update replaces the existing row rather than
accumulating history (unlike this platform's append-only tables; a
preference has no "prior value" worth keeping).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PREFERENCE_COLUMNS = "id, person_ref, channel, topic, enabled, quiet_hours, created_at, updated_at"


async def get_preference(
    session: AsyncSession, *, person_ref: uuid.UUID, channel: str, topic: str
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    f"SELECT {_PREFERENCE_COLUMNS} FROM preferences "  # nosec B608 -- constant columns
                    "WHERE person_ref = :person AND channel = :channel AND topic = :topic"
                ),
                {"person": person_ref, "channel": channel, "topic": topic},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def upsert_preference(
    session: AsyncSession,
    *,
    person_ref: uuid.UUID,
    channel: str,
    topic: str,
    enabled: bool,
    quiet_hours: dict[str, Any] | None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO preferences "  # nosec B608 -- constant columns
                    "  (id, person_ref, channel, topic, enabled, quiet_hours) "
                    "VALUES (:id, :person, :channel, :topic, :enabled, "
                    "        cast(:quiet_hours as jsonb)) "
                    "ON CONFLICT (person_ref, channel, topic) "
                    "DO UPDATE SET enabled = :enabled, "
                    "              quiet_hours = cast(:quiet_hours as jsonb), "
                    "              updated_at = now() "
                    f"RETURNING {_PREFERENCE_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "person": person_ref,
                    "channel": channel,
                    "topic": topic,
                    "enabled": enabled,
                    "quiet_hours": json.dumps(quiet_hours) if quiet_hours is not None else None,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_preferences(session: AsyncSession, *, person_ref: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                text(
                    f"SELECT {_PREFERENCE_COLUMNS} FROM preferences "  # nosec B608 -- constant columns
                    "WHERE person_ref = :person ORDER BY channel, topic"
                ),
                {"person": person_ref},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]
