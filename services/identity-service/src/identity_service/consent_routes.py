"""Consent + guardianship routes (M02 Step 6).

Guardian flow for minors (Book 0 §11.1, AC-M02-04):

1. Minor registers (dob < 18) -> after email verification, status is
   ``pending_consent`` and login is blocked.
2. A guardian (any authenticated adult) creates a guardianship over the
   minor  ->  POST /v1/guardianships.
3. The guardian grants a processing consent for the minor  ->
   POST /v1/consents. That call activates the minor if a verified
   guardianship + this consent both hold. The minor can then log in.
4. Withdrawing the consent (POST /v1/consents/{id}/withdraw) restricts
   the minor back to ``pending_consent``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field

from cip_core import (
    AuthenticatedPrincipal,
    BadRequest,
    Forbidden,
    NotFound,
    audit_record,
    require_authenticated,
    require_idempotency_key,
)
from cip_data import admin_session
from identity_service.deps import Deps, get_deps
from identity_service.domain.consent import (
    PROCESSING,
    activate_minor_if_eligible,
    create_consent,
    create_guardianship,
    get_person_dob_and_status,
    has_verified_guardianship,
    restrict_minor_if_consent_lost,
    withdraw_consent,
)
from identity_service.domain.persons import get_person_by_email

guardianship_router = APIRouter(prefix="/v1/guardianships", tags=["consent"])
consent_router = APIRouter(prefix="/v1/consents", tags=["consent"])


# --- models ---------------------------------------------------------------


class CreateGuardianshipRequest(BaseModel):
    """Identify the minor by email (adult guardian is the authenticated caller)."""

    minor_email: EmailStr


class GuardianshipView(BaseModel):
    id: uuid.UUID
    minor_person_id: uuid.UUID
    guardian_person_id: uuid.UUID
    verified: bool


class CreateConsentRequest(BaseModel):
    minor_person_id: uuid.UUID
    type: str = Field(PROCESSING, description="Consent type; 'processing' gates activation")
    scope: dict[str, Any] = Field(default_factory=dict)


class ConsentView(BaseModel):
    id: uuid.UUID
    minor_person_id: uuid.UUID
    type: str
    minor_status: str = Field(..., description="Minor's status after this consent")


class WithdrawView(BaseModel):
    consent_id: uuid.UUID
    minor_person_id: uuid.UUID
    minor_status: str


# --- routes ---------------------------------------------------------------


@guardianship_router.post(
    "",
    response_model=GuardianshipView,
    status_code=status.HTTP_201_CREATED,
)
async def create_guardianship_endpoint(
    body: CreateGuardianshipRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> GuardianshipView:
    """The authenticated adult claims guardianship over a minor (by email).

    For M02 the link is auto-verified. A guardian cannot claim themselves,
    and the target must be a minor account.
    """
    async with admin_session(deps.session_factory) as session:
        minor = await get_person_by_email(session, body.minor_email)
        if minor is None:
            raise NotFound("No account for that email")
        if minor["id"] == principal.person_id:
            raise BadRequest("You cannot be your own guardian")
        if minor["dob_band"] != "minor":
            raise BadRequest("That account is not a minor account")

        gid = await create_guardianship(
            session,
            minor_person_id=minor["id"],
            guardian_person_id=principal.person_id,
            verified=True,
        )

    return GuardianshipView(
        id=gid,
        minor_person_id=minor["id"],
        guardian_person_id=principal.person_id,
        verified=True,
    )


@consent_router.post(
    "",
    response_model=ConsentView,
    status_code=status.HTTP_201_CREATED,
)
async def create_consent_endpoint(
    body: CreateConsentRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ConsentView:
    """Guardian grants a consent for a minor; activates the minor if eligible.

    The caller must hold a verified guardianship over the minor. This is the
    gate in AC-M02-04: no verified-guardian consent => minor stays blocked.
    """
    async with admin_session(deps.session_factory) as session:
        info = await get_person_dob_and_status(session, person_id=body.minor_person_id)
        if info is None:
            raise NotFound("Minor account not found")
        dob_band, _ = info
        if dob_band != "minor":
            raise BadRequest("Consent gate only applies to minor accounts")

        if not await has_verified_guardianship(
            session,
            minor_person_id=body.minor_person_id,
            guardian_person_id=principal.person_id,
        ):
            raise Forbidden("You must hold a verified guardianship over this minor first")

        consent_id = await create_consent(
            session,
            person_id=body.minor_person_id,
            granted_by=principal.person_id,
            consent_type=body.type,
            scope=body.scope,
        )
        new_status = await activate_minor_if_eligible(session, minor_person_id=body.minor_person_id)
        await audit_record(
            session,
            action="consent.granted",
            entity=f"person:{body.minor_person_id}",
            actor=f"person:{principal.person_id}",
            meta={"type": body.type, "consent_id": str(consent_id)},
        )

    return ConsentView(
        id=consent_id,
        minor_person_id=body.minor_person_id,
        type=body.type,
        minor_status=new_status,
    )


@consent_router.post("/{consent_id}/withdraw", response_model=WithdrawView)
async def withdraw_consent_endpoint(
    consent_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> WithdrawView:
    """Withdraw a consent the caller granted; may restrict the minor again."""
    async with admin_session(deps.session_factory) as session:
        withdrawn = await withdraw_consent(
            session, consent_id=consent_id, by_person_id=principal.person_id
        )
        if withdrawn is None:
            raise NotFound("No active consent with that id granted by you")
        minor_person_id = withdrawn["person_id"]
        new_status = "unaffected"
        if withdrawn["type"] == PROCESSING:
            new_status = await restrict_minor_if_consent_lost(
                session, minor_person_id=minor_person_id
            )
        await audit_record(
            session,
            action="consent.withdrawn",
            entity=f"person:{minor_person_id}",
            actor=f"person:{principal.person_id}",
            meta={"consent_id": str(consent_id)},
        )

    return WithdrawView(
        consent_id=consent_id,
        minor_person_id=minor_person_id,
        minor_status=new_status,
    )
