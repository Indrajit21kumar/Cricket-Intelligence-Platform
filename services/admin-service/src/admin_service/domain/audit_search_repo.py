"""Platform-wide audit-trail search (M20 Step 7, FR-M20-07).

``audit_log``'s RLS keeps a tenant-scoped row invisible outside that
tenant's own session — right everywhere else, wrong for the one place a
platform_admin's job requires it. Migration 0004 (base) added a narrow,
READ-ONLY bypass: a session that sets the ``cip.platform_admin_bypass`` GUC
may SELECT any row; the same session still cannot INSERT/UPDATE outside its
own tenant scope, since the policy's WITH CHECK clause was left untouched.
:func:`search_audit_log` is the one place in the codebase that sets it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def search_audit_log(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID | None = None,
    actor: str | None = None,
    action: str | None = None,
    entity: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Search every tenant's audit trail (read-only cross-tenant bypass)."""
    await session.execute(text("SELECT set_config('cip.platform_admin_bypass', 'true', true)"))
    conditions: list[str] = []
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if tenant_id is not None:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id
    if actor is not None:
        conditions.append("actor = :actor")
        params["actor"] = actor
    if action is not None:
        conditions.append("action = :action")
        params["action"] = action
    if entity is not None:
        conditions.append("entity = :entity")
        params["entity"] = entity
    if since is not None:
        conditions.append("at >= :since")
        params["since"] = since
    if until is not None:
        conditions.append("at <= :until")
        params["until"] = until
    where = f"WHERE {' AND '.join(conditions)} " if conditions else ""
    query = (
        "SELECT id, tenant_id, actor, action, entity, correlation_id, meta, at "
        f"FROM audit_log {where}"  # nosec B608 -- `where` builds only from fixed clause strings
        "ORDER BY at DESC LIMIT :limit OFFSET :offset"
    )
    rows = (await session.execute(text(query), params)).mappings().all()
    return [dict(r) for r in rows]
