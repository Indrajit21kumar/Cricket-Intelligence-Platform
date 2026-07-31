"""Admin-action audit (M20 Step 2, FR-M20-09, NFR-M20-02).

Every privileged admin action gets TWO records: a row in this service's own
``admin_actions`` (fast console-local search/dashboards — richer meta and the
``cross_tenant`` flag NFR-M20-02 calls for) AND a call into ``cip_core``'s
shared audit ledger (``audit_log``) — the same trail every other service's
sensitive actions land in, so a compliance review never has to know
admin-service exists to find an admin's cross-tenant access or impersonation.

Every route in :mod:`admin_service.routes` that performs a privileged action
calls this helper exactly once; nothing here decides WHAT counts as
privileged — that judgement stays at the call site.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import audit_record


async def record_admin_action(
    session: AsyncSession,
    *,
    admin_ref: str,
    action: str,
    target: str,
    tenant_ref: uuid.UUID | None = None,
    cross_tenant: bool = False,
    meta: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Record one privileged admin action. Returns the ``admin_actions`` row id."""
    action_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO admin_actions "
            "  (id, admin_ref, action, target, tenant_ref, cross_tenant, meta) "
            "VALUES (:id, :admin, :action, :target, :tenant, :cross, cast(:meta as jsonb))"
        ),
        {
            "id": action_id,
            "admin": admin_ref,
            "action": action,
            "target": target,
            "tenant": tenant_ref,
            "cross": cross_tenant,
            "meta": json.dumps(meta or {}, default=str),
        },
    )
    if tenant_ref is not None:
        # audit_log's RLS policy (migration 0002) admits a real tenant_id row
        # only when the session's tenant GUC matches it. This call runs under
        # admin_session (no ambient tenant scope — an admin acts FROM OUTSIDE
        # the tenant), so scope this one write to tenant_ref, the same way
        # cip_data.tenant_session does for a normal request.
        await session.execute(
            text("SELECT set_config('cip.tenant_id', :tid, true)"), {"tid": str(tenant_ref)}
        )
    await audit_record(
        session,
        action=f"admin.{action}",
        entity=target,
        actor=admin_ref,
        meta=meta,
        tenant_id=tenant_ref,
    )
    return action_id
