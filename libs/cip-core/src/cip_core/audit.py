"""Audit-logging helper — one call per sensitive action.

Book 3 §5.2 requires audit records for sensitive actions (access to minors'
data, exports, role changes). Every CIP service imports :func:`record` and
calls it with the smallest possible surface — action, entity, optional
meta. Tenant, actor, and correlation_id are pulled from the request
context automatically.

The write goes to the ``audit_log`` table via a SQLAlchemy AsyncSession the
caller passes in. Passing the session keeps this helper independent of
``cip_data`` (avoiding a circular dependency: ``cip_data`` may want to log
audit events during migrations or transactional actions).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core.context import get_correlation_id, require_tenant_id


async def record(
    session: AsyncSession,
    *,
    action: str,
    entity: str,
    actor: str,
    meta: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Write a row to ``audit_log`` under the current tenant + correlation.

    ``session`` MUST be a tenant-scoped session (built via
    :func:`cip_data.tenant_session`) so the row lands under the correct
    tenant and passes the RLS WITH CHECK policy.

    ``action``  — verb of what happened (e.g. ``"role.granted"``,
                  ``"minor.data.exported"``).
    ``entity``  — the affected resource (e.g. ``"player:abc-123"``,
                  ``"tenant:foo"``).
    ``actor``   — who did it (a user_ref, service name, or system id).
    ``meta``    — optional JSON payload for extra context.

    Returns the generated audit row id.
    """
    audit_id = uuid.uuid4()
    tenant_id = require_tenant_id()
    correlation_id = get_correlation_id()

    await session.execute(
        text(
            "INSERT INTO audit_log "
            "  (id, tenant_id, actor, action, entity, correlation_id, meta) "
            "VALUES "
            "  (:id, :tid, :actor, :action, :entity, :cid, "
            "   cast(:meta as jsonb))"
        ),
        {
            "id": audit_id,
            "tid": tenant_id,
            "actor": actor,
            "action": action,
            "entity": entity,
            "cid": correlation_id,
            "meta": _serialise_meta(meta),
        },
    )
    return audit_id


def _serialise_meta(meta: dict[str, Any] | None) -> str:
    """Serialise ``meta`` to a JSON string safe to cast to Postgres JSONB.

    Uses stdlib json — pydantic isn't imported here since audit_log is a
    plain-Python surface (not every service reaches for pydantic).
    """
    if meta is None:
        return "{}"
    import json

    return json.dumps(meta, default=str)
