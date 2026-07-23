"""Profile API routes — M04.

- Step 2: player attribute CRUD + fast attribute read for M10.

Profiles are person-anchored (no tenant RLS), so authorisation is the shared
cip-core consent helper, run *before* any row is touched. All DB access uses
``admin_session`` (the tables have no RLS; the consent check is the gate).

Endpoints:
  POST   /v1/players/{person_id}/profile      create/initialise
  GET    /v1/players/{person_id}/profile       read attributes (consent-scoped)
  PATCH  /v1/players/{person_id}/profile        update attributes
  GET    /v1/players/{person_id}/attributes     internal fast read for M10 (<50ms)

Later steps add DNA (3), snapshots/trends (4), baseline (5), export/delete (6),
and events + audit (7).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import (
    CONSENT_PROCESSING,
    AuthenticatedPrincipal,
    Conflict,
    Forbidden,
    NotFound,
    check_profile_access,
    has_active_consent,
    require_authenticated,
    roles,
)
from cip_data import admin_session
from profile_service.deps import Deps, get_deps
from profile_service.domain.profiles import (
    create_profile,
    get_attributes,
    get_profile_by_person,
    update_attributes,
)

profiles_router = APIRouter(prefix="/v1/players", tags=["profiles"])

# Roles allowed to initialise a profile (onboarding). Creating an empty
# profile is low-risk — the sensitive data (DNA) is written only by M16.
_CREATE_ROLES = (roles.ACADEMY_ADMIN, roles.ORG_ADMIN, roles.PLATFORM_ADMIN)

Stance = Literal["right-hand-bat", "left-hand-bat"]
AgeBand = Literal["u13", "u16", "u19", "senior"]
Hand = Literal["right", "left"]


class ProfileAttributes(BaseModel):
    height_cm: int | None = Field(None, ge=50, le=250)
    stance: Stance | None = None
    age_band: AgeBand | None = None
    dominant_hand: Hand | None = None


class ProfileView(BaseModel):
    id: uuid.UUID
    person_id: uuid.UUID
    height_cm: int | None
    stance: str | None
    age_band: str | None
    dominant_hand: str | None


class AttributesView(BaseModel):
    """Minimal analysis attributes for the M10 fast path."""

    person_id: uuid.UUID
    height_cm: int | None
    stance: str | None
    age_band: str | None
    dominant_hand: str | None


def _view(row: dict[str, Any]) -> ProfileView:
    return ProfileView(
        id=row["id"],
        person_id=row["person_id"],
        height_cm=row["height_cm"],
        stance=row["stance"],
        age_band=row["age_band"],
        dominant_hand=row["dominant_hand"],
    )


async def _require_read_access(
    deps: Deps, *, subject: uuid.UUID, principal: AuthenticatedPrincipal, purpose: str
) -> None:
    """Raise Forbidden unless the principal may access the subject's profile."""
    async with admin_session(deps.session_factory) as session:
        decision = await check_profile_access(
            session,
            subject_person_id=subject,
            reader_person_id=principal.person_id,
            reader_roles=principal.roles,
            purpose=purpose,
        )
    if not decision.allowed:
        raise Forbidden("Not permitted to access this profile", details={"reason": decision.reason})


@profiles_router.post("/{person_id}/profile", response_model=ProfileView, status_code=201)
async def create_player_profile(
    person_id: uuid.UUID,
    body: ProfileAttributes,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ProfileView:
    """Create the 1:1 profile for a person (self, or an onboarding admin)."""
    # Creation policy: self, or an onboarding admin role. (Coaches need an
    # existing profile + sharing consent, so they can't bootstrap one.)
    is_self = principal.person_id == person_id
    is_admin = any(r in _CREATE_ROLES for r in principal.roles)
    if not (is_self or is_admin):
        raise Forbidden("Not permitted to create this profile", details={"reason": "not_permitted"})

    async with admin_session(deps.session_factory) as session:
        existing = await get_profile_by_person(session, person_id)
        if existing is not None:
            raise Conflict("Profile already exists for this person")
        row = await create_profile(
            session,
            person_id=person_id,
            height_cm=body.height_cm,
            stance=body.stance,
            age_band=body.age_band,
            dominant_hand=body.dominant_hand,
        )
    return _view(row)


@profiles_router.get("/{person_id}/profile", response_model=ProfileView)
async def read_player_profile(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ProfileView:
    """Read a player's attributes (consent-scoped)."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read")
    async with admin_session(deps.session_factory) as session:
        row = await get_profile_by_person(session, person_id)
    if row is None:
        raise NotFound("Profile not found")
    return _view(row)


@profiles_router.patch("/{person_id}/profile", response_model=ProfileView)
async def patch_player_profile(
    person_id: uuid.UUID,
    body: ProfileAttributes,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ProfileView:
    """Update a subset of a player's attributes (consent-scoped)."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="write")
    fields = body.model_dump(exclude_unset=True)
    async with admin_session(deps.session_factory) as session:
        row = await update_attributes(session, person_id=person_id, fields=fields)
    if row is None:
        raise NotFound("Profile not found")
    return _view(row)


@profiles_router.get("/{person_id}/attributes", response_model=AttributesView)
async def read_attributes_fast(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> AttributesView:
    """Fast internal attribute read for M10 (<50ms).

    Gated on the SUBJECT having an active 'processing' consent — a reader may
    only pull analysis attributes for a player who consented to processing
    (AC-M04-02: a non-consented reader is denied). Withdrawing processing
    consent immediately denies this path (AC-M04-06).
    """
    _ = principal  # authenticated internal caller (M10)
    async with admin_session(deps.session_factory) as session:
        consented = await has_active_consent(
            session, person_id=person_id, consent_type=CONSENT_PROCESSING
        )
        if not consented:
            raise Forbidden(
                "Subject has not consented to processing",
                details={"reason": "no_consent"},
            )
        attrs = await get_attributes(session, person_id)
    if attrs is None:
        raise NotFound("Profile not found")
    return AttributesView(
        person_id=person_id,
        height_cm=attrs.height_cm,
        stance=attrs.stance,
        age_band=attrs.age_band,
        dominant_hand=attrs.dominant_hand,
    )
