"""DNA snapshots + progress trends (M04 Step 4, FR-M04-07/08, AC-M04-04).

A *snapshot* is a versioned, point-in-time copy of the whole Cricket DNA
(one JSONB blob). M16 takes one after materially updating a player's DNA
(e.g. after a report), giving auditable, immutable checkpoints and the anchor
points for trend charts.

A *trend* is a period-bucketed series of one trait's value over time, built
from the append-only ``dna_trait_history`` — the raw material for the
progress view (weekly / monthly / yearly).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from profile_service.domain.dna import get_current_dna

#: API period -> Postgres date_trunc field.
_PERIOD_TRUNC = {"weekly": "week", "monthly": "month", "yearly": "year"}
VALID_PERIODS = frozenset(_PERIOD_TRUNC)


async def create_snapshot(
    session: AsyncSession, *, profile_id: uuid.UUID, now: datetime | None = None
) -> dict[str, Any]:
    """Capture the current DNA into a new versioned snapshot.

    Version is ``max(version) + 1`` for the profile; the UNIQUE
    (profile_id, version) constraint backstops the read-then-write race
    (single-writer M16 in practice, so contention is nil).
    """
    taken_at = now or datetime.now(UTC)
    traits = await get_current_dna(session, profile_id)
    payload = {
        t["trait_key"]: {
            "value": t["value"],
            "confidence": t["confidence"],
            "provenance": t["provenance"],
        }
        for t in traits
    }
    version = int(
        (
            await session.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM dna_snapshots "
                    "WHERE profile_id = :pid"
                ),
                {"pid": profile_id},
            )
        ).scalar()
        or 1
    )
    await session.execute(
        text(
            "INSERT INTO dna_snapshots (id, profile_id, version, taken_at, payload) "
            "VALUES (:id, :pid, :v, :at, cast(:p as jsonb))"
        ),
        {
            "id": uuid.uuid4(),
            "pid": profile_id,
            "v": version,
            "at": taken_at,
            "p": json.dumps(payload),
        },
    )
    return {"version": version, "taken_at": taken_at, "trait_count": len(payload)}


async def list_snapshots(session: AsyncSession, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT version, taken_at FROM dna_snapshots WHERE profile_id = :pid ORDER BY version"
        ),
        {"pid": profile_id},
    )
    return [dict(r) for r in rows.mappings()]


async def get_snapshot(
    session: AsyncSession, profile_id: uuid.UUID, version: int
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT version, taken_at, payload FROM dna_snapshots "
                    "WHERE profile_id = :pid AND version = :v"
                ),
                {"pid": profile_id, "v": version},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def trait_trend(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID,
    trait_key: str,
    period: str,
) -> list[dict[str, Any]]:
    """Period-bucketed trend of one trait (latest value per bucket).

    ``period`` is one of ``VALID_PERIODS``; the caller validates it (the route
    uses a Literal). The bucket field is passed as a bind param, so no dynamic
    SQL is built.
    """
    trunc = _PERIOD_TRUNC[period]
    rows = await session.execute(
        text(
            "SELECT DISTINCT ON (date_trunc(:trunc, snapshot_at)) "
            "  date_trunc(:trunc, snapshot_at) AS period_start, value, confidence "
            "FROM dna_trait_history "
            "WHERE profile_id = :pid AND trait_key = :key "
            "ORDER BY date_trunc(:trunc, snapshot_at), snapshot_at DESC"
        ),
        {"trunc": trunc, "pid": profile_id, "key": trait_key},
    )
    return [dict(r) for r in rows.mappings()]
