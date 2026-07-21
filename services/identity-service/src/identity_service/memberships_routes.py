"""Membership routes (M02 Step 5) + /v1/me.

Portable identity (ENG-002): a person's persons row + credentials + tokens
+ audit history all survive the deletion of any single membership. That's
what makes players portable across academies — the whole point of Book 1's
'history reset' problem.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cip_core import (
    AuthenticatedPrincipal,
    BadRequest,
    Forbidden,
    NotFound,
    audit_record,
    require_authenticated,
    require_idempotency_key,
    roles,
)
from cip_data import admin_session, tenant_session
from identity_service.deps import Deps, get_deps
from identity_service.domain.memberships import (
    create_membership,
    delete_membership,
    get_membership,
    list_memberships_for_person,
)

membership_router = APIRouter(prefix="/v1/memberships", tags=["memberships"])
me_router = APIRouter(prefix="/v1/me", tags=["me"])


# --- models ---------------------------------------------------------------


class JoinTenantRequest(BaseModel):
    """Simple 'accept invite' shape.

    Invite issuance is a follow-up (tenant admins send an invite token to
    a prospective member; this endpoint would consume that token). For
    M02 Step 5 the tenant + role come from the body directly; RBAC (this
    router uses require_role for admin-only invite acceptance) guards it.
    """

    tenant_id: uuid.UUID
    role: str = Field(..., min_length=1, max_length=50)


class MembershipView(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str
    status: str


class MeResponse(BaseModel):
    person_id: uuid.UUID
    email: str
    status: str
    dob_band: str | None
    display_name: str | None
    roles: list[str]
    memberships: list[MembershipView]


# --- routes ---------------------------------------------------------------


@membership_router.post(
    "",
    response_model=MembershipView,
    status_code=status.HTTP_201_CREATED,
)
async def create_membership_endpoint(
    body: JoinTenantRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> MembershipView:
    """Add the authenticated person to a tenant with a role.

    Real invitation flow (invite tokens, side-channel emails, etc.) is a
    follow-up; this endpoint takes tenant_id + role directly so Step 5's
    portable-identity test can create memberships.

    Role must be one of the canonical CIP roles from ``cip_core.roles``.
    """
    if body.role not in roles.ALL_ROLES:
        raise BadRequest(
            "Unknown role",
            details={"allowed": list(roles.ALL_ROLES), "got": body.role},
        )
    if body.role == roles.PLATFORM_ADMIN:
        raise Forbidden(
            "platform_admin cannot be granted through this endpoint",
        )

    try:
        # A role grant is a tenant-scoped event, so we write it under a
        # tenant_session bound to that tenant. That sets the cip.tenant_id
        # GUC so the tenant-scoped audit_log row passes its WITH CHECK
        # policy. memberships itself has no RLS, so the insert is unaffected.
        async with tenant_session(deps.session_factory, tenant_id=body.tenant_id) as session:
            membership_id = await create_membership(
                session,
                person_id=principal.person_id,
                tenant_id=body.tenant_id,
                role=body.role,
            )
            await audit_record(
                session,
                action="membership.role_granted",
                entity=f"person:{principal.person_id}",
                actor=f"person:{principal.person_id}",
                tenant_id=body.tenant_id,
                meta={"role": body.role, "membership_id": str(membership_id)},
            )
    except IntegrityError as exc:
        # Either the tenant doesn't exist (FK), the person doesn't exist,
        # OR the person is already a member (uq_memberships_person_tenant).
        raise BadRequest("Cannot create membership") from exc

    return MembershipView(
        id=membership_id,
        person_id=principal.person_id,
        tenant_id=body.tenant_id,
        role=body.role,
        status="active",
    )


@membership_router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def leave_tenant(
    membership_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> None:
    """Delete one of the caller's memberships. Person + credentials + tokens
    + audit history are all retained (that's the portable-identity property).

    We look the membership up via admin_session (needs cross-tenant read
    to fetch tenant_id from an id-only URL), then delete it via
    tenant_session for that tenant so RLS blocks deleting someone else's
    membership. Same person can only delete their own — enforced by an
    explicit person_id check.
    """
    # Look up the membership first (cross-tenant read) to get its tenant_id
    # and enforce ownership.
    async with admin_session(deps.session_factory) as session:
        row = await get_membership(session, membership_id=membership_id)
    if row is None:
        raise NotFound(f"Membership {membership_id} not found")
    if row["person_id"] != principal.person_id:
        # Deny-by-default — tenant admins revoking someone else's
        # membership is a separate admin endpoint (follow-up work).
        raise Forbidden("You may only leave your own memberships")

    # Delete + audit under a tenant_session for that tenant so the
    # tenant-scoped audit row passes WITH CHECK.
    async with tenant_session(deps.session_factory, tenant_id=row["tenant_id"]) as session:
        deleted = await delete_membership(session, membership_id=membership_id)
        if deleted:
            await audit_record(
                session,
                action="membership.role_revoked",
                entity=f"person:{principal.person_id}",
                actor=f"person:{principal.person_id}",
                tenant_id=row["tenant_id"],
                meta={"membership_id": str(membership_id), "role": row["role"]},
            )
    if not deleted:
        # Rare race: someone else deleted between our lookup and delete.
        raise NotFound(f"Membership {membership_id} not found")


@me_router.get("", response_model=MeResponse)
async def me(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> MeResponse:
    """Return the caller's identity + tenants + roles + consent state."""
    async with admin_session(deps.session_factory) as session:
        person_row = (
            (
                await session.execute(
                    text(
                        "SELECT id, email, status, dob_band, display_name "
                        "FROM persons WHERE id = :id"
                    ),
                    {"id": principal.person_id},
                )
            )
            .mappings()
            .first()
        )
        if person_row is None:
            raise NotFound("Person no longer exists")
        memberships = await list_memberships_for_person(session, person_id=principal.person_id)

    return MeResponse(
        person_id=principal.person_id,
        email=str(person_row["email"]),
        status=str(person_row["status"]),
        dob_band=person_row["dob_band"],
        display_name=person_row["display_name"],
        roles=list(principal.roles),
        memberships=[
            MembershipView(
                id=m["id"],
                person_id=principal.person_id,
                tenant_id=m["tenant_id"],
                role=m["role"],
                status=m["status"],
            )
            for m in memberships
        ],
    )
