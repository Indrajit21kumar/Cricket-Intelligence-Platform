"""reports + coach_sessions + coach_messages repository (M14 Step 8, §11).

Tenant-scoped (RLS) store. ``reports`` is idempotent on
``(tenant_id, correlation_id)`` so a re-delivered ``analysis.reasoned`` event
updates one row rather than duplicating (mirrors M13's reasoning_results).
Coach sessions/messages are append-only: a session groups a conversation's
turns, each message keeps the citations it grounded on (or none, for a
deferred turn) so every reply stays auditable (§13, AC-M14-03).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_REPORT_COLUMNS = (
    "id, tenant_id, correlation_id, person_id, kg_version, structure, scores, "
    "annotated_video_ref, schema_version, provisional, created_at, updated_at"
)

_SESSION_COLUMNS = "id, tenant_id, person_id, created_at"

_MESSAGE_COLUMNS = "id, tenant_id, coach_session_id, role, content, citations, deferred, created_at"


async def upsert_report(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    correlation_id: str,
    person_id: uuid.UUID | None,
    kg_version: str,
    structure: dict[str, Any],
    scores: dict[str, Any],
    annotated_video_ref: str | None,
    schema_version: str,
    provisional: bool,
) -> dict[str, Any]:
    """Idempotent upsert on (tenant_id, correlation_id)."""
    row = (
        (
            await session.execute(
                text(
                    # Only the module-level _REPORT_COLUMNS constant is interpolated.
                    "INSERT INTO reports "  # nosec B608
                    "  (id, tenant_id, correlation_id, person_id, kg_version, structure, "
                    "   scores, annotated_video_ref, schema_version, provisional) "
                    "VALUES (:id, :tid, :corr, :pid, :kgv, cast(:st as jsonb), "
                    "        cast(:sc as jsonb), :avr, :sv, :prov) "
                    "ON CONFLICT (tenant_id, correlation_id) DO UPDATE SET "
                    "  person_id = EXCLUDED.person_id, kg_version = EXCLUDED.kg_version, "
                    "  structure = EXCLUDED.structure, scores = EXCLUDED.scores, "
                    "  annotated_video_ref = EXCLUDED.annotated_video_ref, "
                    "  schema_version = EXCLUDED.schema_version, "
                    "  provisional = EXCLUDED.provisional, updated_at = now() "
                    f"RETURNING {_REPORT_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "corr": correlation_id,
                    "pid": person_id,
                    "kgv": kg_version,
                    "st": json.dumps(structure),
                    "sc": json.dumps(scores),
                    "avr": annotated_video_ref,
                    "sv": schema_version,
                    "prov": provisional,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_report(session: AsyncSession, correlation_id: str) -> dict[str, Any] | None:
    query = f"SELECT {_REPORT_COLUMNS} FROM reports WHERE correlation_id = :corr"  # nosec B608
    row = (await session.execute(text(query), {"corr": correlation_id})).mappings().first()
    return dict(row) if row else None


async def create_coach_session(
    session: AsyncSession, *, tenant_id: uuid.UUID, person_id: uuid.UUID
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO coach_sessions (id, tenant_id, person_id) "
                    "VALUES (:id, :tid, :pid) "
                    f"RETURNING {_SESSION_COLUMNS}"  # nosec B608 -- constant columns
                ),
                {"id": uuid.uuid4(), "tid": tenant_id, "pid": person_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_coach_session(
    session: AsyncSession, coach_session_id: uuid.UUID
) -> dict[str, Any] | None:
    query = f"SELECT {_SESSION_COLUMNS} FROM coach_sessions WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": coach_session_id})).mappings().first()
    return dict(row) if row else None


async def append_coach_message(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    coach_session_id: uuid.UUID,
    role: str,
    content: str,
    citations: list[str],
    deferred: bool,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO coach_messages "
                    "  (id, tenant_id, coach_session_id, role, content, citations, deferred) "
                    "VALUES (:id, :tid, :sid, :role, :content, cast(:cit as jsonb), :deferred) "
                    f"RETURNING {_MESSAGE_COLUMNS}"  # nosec B608 -- constant columns
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "sid": coach_session_id,
                    "role": role,
                    "content": content,
                    "cit": json.dumps(citations),
                    "deferred": deferred,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def list_coach_messages(
    session: AsyncSession, coach_session_id: uuid.UUID
) -> list[dict[str, Any]]:
    query = (
        f"SELECT {_MESSAGE_COLUMNS} FROM coach_messages "  # nosec B608 -- constant columns
        "WHERE coach_session_id = :sid ORDER BY created_at ASC"
    )
    rows = (await session.execute(text(query), {"sid": coach_session_id})).mappings().all()
    return [dict(row) for row in rows]
