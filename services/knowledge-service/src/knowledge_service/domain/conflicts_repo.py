"""rule_conflicts repository (M12 Step 7, §6, FR-M12-07).

When two released rules can fire on the same facts with different risks, the
conflict is RECORDED with a precedence (which rule_id wins) so the Reasoning
Engine resolves it deterministically, and it is surfaced to reviewers until
resolved. Global store, so all calls run under ``admin_session``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, rule_a, rule_b, precedence, note, resolved, created_at, updated_at"


async def upsert_conflict(
    session: AsyncSession,
    *,
    rule_a: str,
    rule_b: str,
    precedence: str | None,
    note: str | None,
) -> dict[str, Any]:
    """Record (or update) a conflict between two rules on (rule_a, rule_b)."""
    resolved = precedence is not None
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO rule_conflicts (id, rule_a, rule_b, precedence, note, resolved) "
                    "VALUES (:id, :ra, :rb, :prec, :note, :resolved) "
                    "ON CONFLICT (rule_a, rule_b) DO UPDATE SET "
                    "  precedence = EXCLUDED.precedence, note = EXCLUDED.note, "
                    "  resolved = EXCLUDED.resolved, updated_at = now() "
                    f"RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {
                    "id": uuid.uuid4(),
                    "ra": rule_a,
                    "rb": rule_b,
                    "prec": precedence,
                    "note": note,
                    "resolved": resolved,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_conflict(session: AsyncSession, conflict_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM rule_conflicts WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": conflict_id})).mappings().first()
    return dict(row) if row else None


async def resolve_conflict(
    session: AsyncSession, conflict_id: uuid.UUID, *, precedence: str, note: str | None
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE rule_conflicts SET precedence = :prec, "  # nosec B608
                    "  note = COALESCE(:note, note), resolved = true, updated_at = now() "
                    f"WHERE id = :id RETURNING {_COLUMNS}"
                ),
                {"id": conflict_id, "prec": precedence, "note": note},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def list_conflicts(
    session: AsyncSession, *, unresolved_only: bool = False
) -> list[dict[str, Any]]:
    where = "WHERE NOT resolved " if unresolved_only else ""
    query = f"SELECT {_COLUMNS} FROM rule_conflicts {where}ORDER BY created_at"  # nosec B608
    rows = (await session.execute(text(query))).mappings().all()
    return [dict(r) for r in rows]
