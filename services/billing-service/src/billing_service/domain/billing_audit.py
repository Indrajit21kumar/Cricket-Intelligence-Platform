"""Immutable billing audit log (M03 Step 8, FR-M03-10, AC-M03-07).

Every billing action — subscribe / plan-change / cancel / invoice reconciled /
seat allocate/deallocate — writes one row to ``billing_audit``. The row
carries actor + correlation_id (from cip_core.context) + JSON meta so ops
can reconstruct exactly who did what, when, and in response to which
request.

Immutable in practice: this table is INSERT-ONLY from application code.
There's no update/delete API here — a correction adds a new row (a
"reversal") rather than mutating history.

We don't dual-write to M01's ``audit_log`` — ``billing_audit`` is the
authoritative M03 record and carries richer meta than the platform log.
Cross-service audit queries join by correlation_id.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core.context import get_correlation_id


async def write_audit(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor: str,
    action: str,
    entity: str,
    meta: dict[str, Any] | None = None,
) -> uuid.UUID:
    """Append one row to ``billing_audit`` and return its id.

    ``correlation_id`` is pulled from the current request context so callers
    don't have to thread it through every function signature.
    """
    audit_id = uuid.uuid4()
    correlation_id = get_correlation_id()
    await session.execute(
        text(
            "INSERT INTO billing_audit "
            "  (id, tenant_id, actor, action, entity, correlation_id, meta) "
            "VALUES (:id, :tid, :actor, :action, :entity, :cid, cast(:meta as jsonb))"
        ),
        {
            "id": audit_id,
            "tid": tenant_id,
            "actor": actor,
            "action": action,
            "entity": entity,
            "cid": correlation_id,
            "meta": json.dumps(meta or {}, default=str),
        },
    )
    return audit_id
