"""Account lifecycle routes (M02 Step 8) — suspend, delete, export.

Book 3 §5.3 + FR-M02-07: a person can suspend their account, request
deletion, or request a data export. Each is a sensitive action recorded in
``audit_log`` with actor + correlation_id (AC-M02-07).

Deletion + export are *requests* here — the actual erasure/packaging is an
async workflow owned by the data-policy pipeline (with M04's Cricket DNA
store, retention rules, and residency). M02 records the request + flips the
account status; downstream consumers act on the emitted intent.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from cip_core import (
    AuthenticatedPrincipal,
    audit_record,
    require_authenticated,
)
from cip_data import admin_session
from identity_service.deps import Deps, get_deps

lifecycle_router = APIRouter(prefix="/v1/me", tags=["lifecycle"])


class LifecycleResponse(BaseModel):
    person_id: uuid.UUID
    status: str
    action: str


async def _set_status_and_audit(
    deps: Deps,
    *,
    person_id: uuid.UUID,
    new_status: str,
    action: str,
) -> LifecycleResponse:
    async with admin_session(deps.session_factory) as session:
        await session.execute(
            text("UPDATE persons SET status = :s, updated_at = now() WHERE id = :id"),
            {"s": new_status, "id": person_id},
        )
        await audit_record(
            session,
            action=action,
            entity=f"person:{person_id}",
            actor=f"person:{person_id}",
        )
    return LifecycleResponse(person_id=person_id, status=new_status, action=action)


@lifecycle_router.post("/suspend", response_model=LifecycleResponse)
async def suspend(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> LifecycleResponse:
    """Suspend the caller's own account (status -> suspended)."""
    return await _set_status_and_audit(
        deps,
        person_id=principal.person_id,
        new_status="suspended",
        action="account.suspended",
    )


@lifecycle_router.post("/deletion-request", response_model=LifecycleResponse)
async def deletion_request(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> LifecycleResponse:
    """Request account deletion (status -> deletion_requested; audited).

    The actual erasure is handled by the data-policy pipeline; this records
    the intent + audits it (GDPR-style right to erasure).
    """
    return await _set_status_and_audit(
        deps,
        person_id=principal.person_id,
        new_status="deletion_requested",
        action="account.deletion_requested",
    )


@lifecycle_router.post("/export-request", response_model=LifecycleResponse)
async def export_request(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> LifecycleResponse:
    """Request a data export (audited; status unchanged).

    The export package is assembled asynchronously; this records the request.
    """
    async with admin_session(deps.session_factory) as session:
        row = (
            await session.execute(
                text("SELECT status FROM persons WHERE id = :id"),
                {"id": principal.person_id},
            )
        ).first()
        current_status = row[0] if row else "unknown"
        await audit_record(
            session,
            action="account.export_requested",
            entity=f"person:{principal.person_id}",
            actor=f"person:{principal.person_id}",
        )
    return LifecycleResponse(
        person_id=principal.person_id,
        status=current_status,
        action="account.export_requested",
    )
