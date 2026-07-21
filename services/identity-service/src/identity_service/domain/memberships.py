"""Membership repository — person <-> tenant with a role.

memberships is the tenant-scoped table that binds a person to a tenant.
Because it's RLS-protected, callers use :func:`cip_data.tenant_session`
for tenant-scoped ops. The role-lookup helper for a person (used to
populate the JWT ``roles`` claim on login) MUST run under
:func:`cip_data.admin_session` — a person's global role set spans
tenants, and RLS would otherwise filter to just one.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_membership(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
) -> uuid.UUID:
    """Insert a ``memberships`` row. Caller must be in a tenant_session
    scoped to ``tenant_id`` (RLS enforces).
    """
    membership_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO memberships (id, person_id, tenant_id, role) "
            "VALUES (:id, :pid, :tid, :role)"
        ),
        {"id": membership_id, "pid": person_id, "tid": tenant_id, "role": role},
    )
    return membership_id


async def delete_membership(session: AsyncSession, *, membership_id: uuid.UUID) -> bool:
    """Remove a single membership. Returns True if a row was actually removed."""
    result = await session.execute(
        text("DELETE FROM memberships WHERE id = :id RETURNING id"),
        {"id": membership_id},
    )
    return result.first() is not None


async def get_membership(
    session: AsyncSession, *, membership_id: uuid.UUID
) -> dict[str, Any] | None:
    """Return a membership row by id, or None."""
    result = await session.execute(
        text("SELECT id, person_id, tenant_id, role, status FROM memberships WHERE id = :id"),
        {"id": membership_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def list_memberships_for_person(
    session: AsyncSession, *, person_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return every membership for a person — CROSS-TENANT.

    MUST run under :func:`cip_data.admin_session` because tenant-scoped
    RLS filters to a single tenant. Consumers: JWT issuance (roles
    across all tenants) and GET /v1/me.
    """
    result = await session.execute(
        text(
            "SELECT id, tenant_id, role, status "
            "FROM memberships WHERE person_id = :pid ORDER BY created_at"
        ),
        {"pid": person_id},
    )
    return [dict(row) for row in result.mappings()]


async def list_roles_for_person(session: AsyncSession, *, person_id: uuid.UUID) -> list[str]:
    """Return the distinct role names a person holds across all tenants.

    Used at login/refresh to populate the JWT ``roles`` claim. Order is
    deterministic (alphabetical) so JWTs for the same principal are
    stable — helps caching + change-detection downstream.
    """
    result = await session.execute(
        text(
            "SELECT DISTINCT role FROM memberships "
            "WHERE person_id = :pid AND status = 'active' ORDER BY role"
        ),
        {"pid": person_id},
    )
    return [row[0] for row in result]
