"""training_plans / plan_evaluations repository (M17 Step 7, §9).

Tenant-scoped (RLS), like every consumer session in this build.
``UNIQUE(tenant_id, person_id, session_ref)`` is the idempotency anchor
(NFR-M17-03) callers check via :func:`get_plan_by_session` before doing any
work. Plans are append-only: a new cycle inserts a fresh row and
:func:`deactivate_plan` flips the OLD one's ``active`` flag — the row itself
is never rewritten (SR-001, longitudinal history).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_PLAN_COLUMNS = (
    "id, tenant_id, person_id, session_ref, stage, items, targets, active, "
    "schema_version, created_at, updated_at"
)


async def get_plan_by_session(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID | None, session_ref: str
) -> dict[str, Any] | None:
    query = (
        f"SELECT {_PLAN_COLUMNS} FROM training_plans "  # nosec B608 -- constant columns
        "WHERE tenant_id = :tid AND person_id IS NOT DISTINCT FROM :pid AND session_ref = :ref"
    )
    row = (
        (
            await session.execute(
                text(query), {"tid": tenant_id, "pid": person_id, "ref": session_ref}
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def get_active_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID | None
) -> dict[str, Any] | None:
    query = (
        f"SELECT {_PLAN_COLUMNS} FROM training_plans "  # nosec B608 -- constant columns
        "WHERE tenant_id = :tid AND person_id IS NOT DISTINCT FROM :pid AND active "
        "ORDER BY created_at DESC LIMIT 1"
    )
    row = (
        (await session.execute(text(query), {"tid": tenant_id, "pid": person_id}))
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def insert_plan(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID | None,
    session_ref: str,
    stage: str,
    items: list[dict[str, Any]],
    schema_version: str,
) -> dict[str, Any]:
    targets = [item["target_ref"] for item in items if isinstance(item.get("target_ref"), str)]
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO training_plans "  # nosec B608 -- constant columns
                    "  (id, tenant_id, person_id, session_ref, stage, items, "
                    "   targets, schema_version) "
                    "VALUES (:id, :tid, :pid, :ref, :stage, cast(:items as jsonb), "
                    "        cast(:targets as jsonb), :sv) "
                    f"RETURNING {_PLAN_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "pid": person_id,
                    "ref": session_ref,
                    "stage": stage,
                    "items": json.dumps(items),
                    "targets": json.dumps(targets),
                    "sv": schema_version,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def deactivate_plan(
    session: AsyncSession, *, tenant_id: uuid.UUID, plan_id: uuid.UUID
) -> None:
    await session.execute(
        text(
            "UPDATE training_plans SET active = false, updated_at = now() "
            "WHERE tenant_id = :tid AND id = :id"
        ),
        {"tid": tenant_id, "id": plan_id},
    )


async def record_evaluation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    plan_id: uuid.UUID,
    target_ref: str,
    met: bool,
    evidence_ref: str | None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO plan_evaluations (id, tenant_id, plan_id, target_ref, met, evidence_ref) "
            "VALUES (:id, :tid, :pid, :ref, :met, :evidence)"
        ),
        {
            "id": uuid.uuid4(),
            "tid": tenant_id,
            "pid": plan_id,
            "ref": target_ref,
            "met": met,
            "evidence": evidence_ref,
        },
    )
