"""rule_versions repository — immutable release snapshots (M12 Step 4, §12).

Releasing a rule freezes its exact content into ``rule_versions`` and flips the
``released`` pin. The snapshot is never mutated or deleted, even when the rule is
later superseded — that permanence is what lets a past report be reproduced
against the exact rule version that produced it (AC-M12-03).

Global store, so all calls run under ``admin_session``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_COLUMNS = "id, rule_id, version, snapshot, released, created_at"


async def freeze_snapshot(
    session: AsyncSession,
    *,
    rule_id: str,
    version: int,
    snapshot: dict[str, Any],
    released: bool,
) -> dict[str, Any]:
    """Insert (or re-affirm) the immutable snapshot for a released version.

    On conflict the snapshot content stays frozen; only the ``released`` pin is
    updated — a superseded version keeps its original snapshot for audit.
    """
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO rule_versions (id, rule_id, version, snapshot, released) "
                    "VALUES (:id, :rid, :ver, cast(:snap as jsonb), :rel) "
                    "ON CONFLICT (rule_id, version) DO UPDATE SET released = EXCLUDED.released "
                    f"RETURNING {_COLUMNS}"  # nosec B608 -- _COLUMNS is a constant
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": rule_id,
                    "ver": version,
                    "snap": json.dumps(snapshot),
                    "rel": released,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def mark_unreleased(session: AsyncSession, *, rule_id: str, version: int) -> None:
    await session.execute(
        text("UPDATE rule_versions SET released = false WHERE rule_id = :rid AND version = :ver"),
        {"rid": rule_id, "ver": version},
    )


async def update_confidence(
    session: AsyncSession, *, rule_id: str, version: int, confidence: float
) -> None:
    """Drift the confidence on a released snapshot.

    Confidence is the one field §6 allows to evolve independently of the version
    content (evidence adjustment), so updating it does NOT fork a version and
    does NOT touch the conditions/fault/cause/risk/drill the reproduction
    guarantee protects — only the number the served graph reports.
    """
    await session.execute(
        text(
            "UPDATE rule_versions "
            "SET snapshot = jsonb_set(snapshot, '{confidence}', to_jsonb(:conf::double precision)) "
            "WHERE rule_id = :rid AND version = :ver"
        ),
        {"rid": rule_id, "ver": version, "conf": confidence},
    )


async def get_released(session: AsyncSession, rule_id: str) -> dict[str, Any] | None:
    query = (
        f"SELECT {_COLUMNS} FROM rule_versions "  # nosec B608 -- _COLUMNS is a constant
        "WHERE rule_id = :rid AND released ORDER BY version DESC LIMIT 1"
    )
    row = (await session.execute(text(query), {"rid": rule_id})).mappings().first()
    return dict(row) if row else None


async def list_released(session: AsyncSession) -> list[dict[str, Any]]:
    """Every released snapshot across all rules — the served (pinned) graph."""
    query = (
        f"SELECT {_COLUMNS} FROM rule_versions "  # nosec B608 -- _COLUMNS is a constant
        "WHERE released ORDER BY rule_id, version"
    )
    rows = (await session.execute(text(query))).mappings().all()
    return [dict(r) for r in rows]


async def list_snapshots(session: AsyncSession, rule_id: str) -> list[dict[str, Any]]:
    query = (
        f"SELECT {_COLUMNS} FROM rule_versions "  # nosec B608 -- _COLUMNS is a constant
        "WHERE rule_id = :rid ORDER BY version"
    )
    rows = (await session.execute(text(query), {"rid": rule_id})).mappings().all()
    return [dict(r) for r in rows]
