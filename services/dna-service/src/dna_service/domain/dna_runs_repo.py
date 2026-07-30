"""dna_update_runs repository (M16 Step 7, §9).

Person-anchored, no RLS (mirrors M04's player_profiles — see migration
0001's docstring). ``admin_session`` access; ``UNIQUE(player_id,
session_ref)`` is the idempotency anchor :func:`get_run` checks against
before any trait write (NFR-M16-03).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, player_id, session_ref, traits_updated, model_version, computed_at"


async def record_run(
    session: AsyncSession,
    *,
    player_id: uuid.UUID,
    session_ref: str,
    traits_updated: dict[str, Any],
    model_version: str,
) -> dict[str, Any]:
    """Insert one processing-log row. Callers MUST check :func:`get_run` first
    (NFR-M16-03) — this does not itself dedupe beyond the DB's unique
    constraint, which would raise on a genuine re-delivery race."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO dna_update_runs "  # nosec B608 -- constant columns
                    "  (id, player_id, session_ref, traits_updated, model_version) "
                    "VALUES (:id, :pid, :ref, cast(:traits as jsonb), :mv) "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "pid": player_id,
                    "ref": session_ref,
                    "traits": json.dumps(traits_updated),
                    "mv": model_version,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_run(
    session: AsyncSession, *, player_id: uuid.UUID, session_ref: str
) -> dict[str, Any] | None:
    query = (
        f"SELECT {_COLUMNS} FROM dna_update_runs "  # nosec B608 -- constant columns
        "WHERE player_id = :pid AND session_ref = :ref"
    )
    row = (
        (await session.execute(text(query), {"pid": player_id, "ref": session_ref}))
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def list_runs(session: AsyncSession, *, player_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every processing-log row for this player, oldest first (replay order)."""
    query = (
        f"SELECT {_COLUMNS} FROM dna_update_runs "  # nosec B608 -- constant columns
        "WHERE player_id = :pid ORDER BY computed_at ASC"
    )
    rows = (await session.execute(text(query), {"pid": player_id})).mappings().all()
    return [dict(row) for row in rows]
