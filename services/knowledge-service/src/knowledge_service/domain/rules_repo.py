"""rules table repository (M12 Step 3+).

The knowledge graph is global (no RLS), so every call runs under
``admin_session`` — ``cip_app`` sees all rows and access is governed by RBAC at
the API layer, not by the row. Rows are keyed by the DB ``id`` (a specific
rule version); ``rule_id`` is the stable logical id shared across versions.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from knowledge_service.domain.rule_schema import Rule

_COLUMNS = (
    "id, rule_id, version, conditions, fault, cause, risk, drill, confidence, "
    "status, author, reviewer, created_at, updated_at"
)


async def insert_rule(session: AsyncSession, rule: Rule, *, author: str | None) -> dict[str, Any]:
    """Insert a new rule row (a draft) and return it."""
    row = (
        (
            await session.execute(
                text(
                    # Only the _COLUMNS constant is interpolated; all values bind.
                    "INSERT INTO rules "  # nosec B608
                    "  (id, rule_id, version, conditions, fault, cause, risk, drill, "
                    "   confidence, status, author) "
                    "VALUES (:id, :rid, :ver, cast(:cond as jsonb), :fault, :cause, "
                    "        cast(:risk as jsonb), cast(:drill as jsonb), :conf, :status, :author) "
                    f"RETURNING {_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": rule.rule_id,
                    "ver": rule.version,
                    "cond": json.dumps([c.to_dict() for c in rule.conditions]),
                    "fault": rule.fault,
                    "cause": rule.cause,
                    "risk": json.dumps(rule.risk.to_dict()),
                    "drill": json.dumps(rule.drill.to_dict()),
                    "conf": rule.confidence,
                    "status": rule.status,
                    "author": author,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_by_id(session: AsyncSession, row_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM rules WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": row_id})).mappings().first()
    return dict(row) if row else None


async def get_version(session: AsyncSession, rule_id: str, version: int) -> dict[str, Any] | None:
    query = f"SELECT {_COLUMNS} FROM rules WHERE rule_id = :rid AND version = :ver"  # nosec B608
    row = (await session.execute(text(query), {"rid": rule_id, "ver": version})).mappings().first()
    return dict(row) if row else None


async def list_versions(session: AsyncSession, rule_id: str) -> list[dict[str, Any]]:
    query = f"SELECT {_COLUMNS} FROM rules WHERE rule_id = :rid ORDER BY version"  # nosec B608
    rows = (await session.execute(text(query), {"rid": rule_id})).mappings().all()
    return [dict(r) for r in rows]


async def update_content(session: AsyncSession, row_id: uuid.UUID, rule: Rule) -> dict[str, Any]:
    """Replace a draft's editable content (never its status/version)."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE rules SET "  # nosec B608
                    "  conditions = cast(:cond as jsonb), fault = :fault, cause = :cause, "
                    "  risk = cast(:risk as jsonb), drill = cast(:drill as jsonb), "
                    "  confidence = :conf, updated_at = now() "
                    f"WHERE id = :id RETURNING {_COLUMNS}"
                ),
                {
                    "id": row_id,
                    "cond": json.dumps([c.to_dict() for c in rule.conditions]),
                    "fault": rule.fault,
                    "cause": rule.cause,
                    "risk": json.dumps(rule.risk.to_dict()),
                    "drill": json.dumps(rule.drill.to_dict()),
                    "conf": rule.confidence,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def set_status(
    session: AsyncSession, row_id: uuid.UUID, status: str, *, reviewer: str | None = None
) -> dict[str, Any]:
    """Move a rule to a new lifecycle status (optionally recording the reviewer)."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE rules SET status = :status, "  # nosec B608
                    "  reviewer = COALESCE(:reviewer, reviewer), updated_at = now() "
                    f"WHERE id = :id RETURNING {_COLUMNS}"
                ),
                {"id": row_id, "status": status, "reviewer": reviewer},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)
