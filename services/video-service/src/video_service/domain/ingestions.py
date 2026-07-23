"""Ingestion repository (M05 Step 2).

``ingestions`` is tenant-scoped (RLS), so all reads/writes run inside a
:func:`cip_data.tenant_session` bound to the clip's tenant. Create is
idempotent on ``(tenant_id, correlation_id)`` — a retried upload with the
same correlation id returns the existing ingestion rather than a duplicate
(NFR-M05-05).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Status lifecycle for an ingestion.
STATUS_CREATED = "created"
STATUS_UPLOADED = "uploaded"
STATUS_PROCESSING = "processing"
STATUS_NORMALIZED = "normalized"
STATUS_REJECTED = "rejected"
STATUS_FAILED = "failed"


async def create_ingestion(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    person_id: uuid.UUID,
    correlation_id: str,
    source_type: str,
    content_type: str | None,
    size_bytes: int | None,
    raw_ref: str,
) -> tuple[dict[str, Any], bool]:
    """Create an ingestion (idempotent on correlation_id). Returns (row, created)."""
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO ingestions "
                    "  (id, tenant_id, person_id, correlation_id, source_type, "
                    "   raw_ref, status, content_type, size_bytes) "
                    "VALUES (:id, :tid, :pid, :corr, :src, :raw, :status, :ct, :sz) "
                    "ON CONFLICT (tenant_id, correlation_id) DO NOTHING "
                    "RETURNING id, tenant_id, person_id, correlation_id, source_type, "
                    "raw_ref, status, content_type, size_bytes, created_at, updated_at"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "pid": person_id,
                    "corr": correlation_id,
                    "src": source_type,
                    "raw": raw_ref,
                    "status": STATUS_CREATED,
                    "ct": content_type,
                    "sz": size_bytes,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is not None:
        return dict(row), True

    existing = (
        (
            await session.execute(
                text(
                    "SELECT id, tenant_id, person_id, correlation_id, source_type, "
                    "raw_ref, status, content_type, size_bytes, created_at, updated_at "
                    "FROM ingestions WHERE correlation_id = :corr"
                ),
                {"corr": correlation_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(existing), False


async def get_ingestion(session: AsyncSession, ingestion_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, tenant_id, person_id, correlation_id, source_type, "
                    "raw_ref, status, content_type, size_bytes, created_at, updated_at "
                    "FROM ingestions WHERE id = :id"
                ),
                {"id": ingestion_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def set_status(
    session: AsyncSession, ingestion_id: uuid.UUID, status: str
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE ingestions SET status = :s, updated_at = now() "
                    "WHERE id = :id "
                    "RETURNING id, tenant_id, person_id, correlation_id, source_type, "
                    "raw_ref, status, content_type, size_bytes, created_at, updated_at"
                ),
                {"s": status, "id": ingestion_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None
