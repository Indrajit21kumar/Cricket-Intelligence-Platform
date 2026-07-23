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
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import (
    CONSENT_PROCESSING,
    AuthenticatedPrincipal,
    BadRequest,
    Conflict,
    Forbidden,
    NotFound,
    check_profile_access,
    has_active_consent,
    require_authenticated,
    require_role,
    roles,
)
from cip_data import admin_session
from profile_service.deps import Deps, get_deps
from profile_service.domain.baseline import (
    get_baseline,
    is_valid_metric_id,
    list_baselines,
    record_observation,
)
from profile_service.domain.dna import (
    PROVENANCE_VALUES,
    TraitUpdate,
    get_current_dna,
    get_trait_history,
    reconstruct_dna_at,
    write_traits,
)
from profile_service.domain.profiles import (
    create_profile,
    get_attributes,
    get_profile_by_person,
    update_attributes,
)
from profile_service.domain.snapshots import (
    create_snapshot,
    get_snapshot,
    list_snapshots,
    trait_trend,
)

profiles_router = APIRouter(prefix="/v1/players", tags=["profiles"])

# Roles allowed to initialise a profile (onboarding). Creating an empty
# profile is low-risk — the sensitive data (DNA) is written only by M16.
_CREATE_ROLES = (roles.ACADEMY_ADMIN, roles.ORG_ADMIN, roles.PLATFORM_ADMIN)

# The service identity M16 (Cricket DNA engine) presents to write traits.
# It is NOT one of the six human roles — only M16's token carries this scope,
# which is what makes "only M16 can write traits" (AC-M04-03) enforceable.
DNA_WRITER_ROLE = "service.cricket_dna"

# The analysis pipeline (M10 / physics) presents this scope to record metric
# observations that build the personal baseline.
BASELINE_WRITER_ROLE = "service.metrics"

Stance = Literal["right-hand-bat", "left-hand-bat"]
AgeBand = Literal["u13", "u16", "u19", "senior"]
Hand = Literal["right", "left"]
Provenance = Literal["measured", "estimated", "modelled"]
Period = Literal["weekly", "monthly", "yearly"]


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


# --- Cricket DNA (M04 Step 3, AC-M04-03, FR-M04-03/04) ----------------------


class TraitUpdateIn(BaseModel):
    trait_key: str = Field(..., min_length=1, description="e.g. 'trait.aggression'")
    value: str = Field(..., description="Stringified score/label (trait-typed)")
    provenance: Provenance
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    source_ref: str | None = Field(None, description="e.g. 'report:<uuid>'")


class WriteDNARequest(BaseModel):
    updates: list[TraitUpdateIn] = Field(..., min_length=1)


class WriteDNAResponse(BaseModel):
    written: int


class TraitView(BaseModel):
    trait_key: str
    value: str
    confidence: float | None
    provenance: str
    source_ref: str | None = None
    updated_at: datetime | None = None
    snapshot_at: datetime | None = None


async def _resolve_profile_id(deps: Deps, person_id: uuid.UUID) -> uuid.UUID:
    async with admin_session(deps.session_factory) as session:
        profile = await get_profile_by_person(session, person_id)
    if profile is None:
        raise NotFound("Profile not found")
    return profile["id"]  # type: ignore[no-any-return]


@profiles_router.post("/{person_id}/dna", response_model=WriteDNAResponse, status_code=201)
async def write_dna(
    person_id: uuid.UUID,
    body: WriteDNARequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(DNA_WRITER_ROLE))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> WriteDNAResponse:
    """Internal: M16 writes trait updates (only the DNA-engine role, AC-M04-03).

    Each update UPSERTs the current value and appends an immutable history row
    (NFR-M04-02). Provenance + confidence come from M16 (FR-M04-04).
    """
    _ = principal  # the require_role gate is the "only M16" enforcement
    # Belt-and-braces: reject unknown provenance values (pydantic Literal
    # already constrains this, but the domain constant is the source of truth).
    for u in body.updates:
        if u.provenance not in PROVENANCE_VALUES:
            raise Forbidden("Invalid provenance", details={"provenance": u.provenance})

    profile_id = await _resolve_profile_id(deps, person_id)
    updates = [
        TraitUpdate(
            trait_key=u.trait_key,
            value=u.value,
            provenance=u.provenance,
            confidence=u.confidence,
            source_ref=u.source_ref,
        )
        for u in body.updates
    ]
    async with admin_session(deps.session_factory) as session:
        written = await write_traits(session, profile_id=profile_id, updates=updates)
    return WriteDNAResponse(written=written)


@profiles_router.get("/{person_id}/dna", response_model=list[TraitView])
async def read_dna(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[TraitView]:
    """Read the player's current Cricket DNA (consent-scoped)."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read_dna")
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        traits = await get_current_dna(session, profile_id)
    return [TraitView(**t) for t in traits]


@profiles_router.get("/{person_id}/dna/history", response_model=list[TraitView])
async def read_dna_history(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
    trait_key: str | None = None,
    at: datetime | None = None,
) -> list[TraitView]:
    """Read trait history, or reconstruct the DNA as of ``at`` (NFR-M04-02).

    - ``?trait_key=`` filters history to one trait.
    - ``?at=`` (ISO-8601) returns the reconstructed value per trait as of that
      instant instead of the full history.
    """
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read_dna")
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        if at is not None:
            rows = await reconstruct_dna_at(session, profile_id, at)
        else:
            rows = await get_trait_history(session, profile_id, trait_key=trait_key)
    return [TraitView(**r) for r in rows]


# --- DNA snapshots + progress trends (M04 Step 4, AC-M04-04, FR-M04-07/08) ---


class SnapshotSummary(BaseModel):
    version: int
    taken_at: datetime
    trait_count: int | None = None


class SnapshotDetail(BaseModel):
    version: int
    taken_at: datetime
    payload: dict[str, Any]


class TrendPoint(BaseModel):
    period_start: datetime
    value: str
    confidence: float | None = None


@profiles_router.post("/{person_id}/dna/snapshots", response_model=SnapshotSummary, status_code=201)
async def take_dna_snapshot(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(DNA_WRITER_ROLE))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> SnapshotSummary:
    """Internal: M16 captures a versioned point-in-time snapshot of the DNA."""
    _ = principal
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        result = await create_snapshot(session, profile_id=profile_id)
    return SnapshotSummary(
        version=result["version"],
        taken_at=result["taken_at"],
        trait_count=result["trait_count"],
    )


@profiles_router.get("/{person_id}/dna/snapshots", response_model=list[SnapshotSummary])
async def list_dna_snapshots(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[SnapshotSummary]:
    """List snapshot versions for a player (consent-scoped)."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read_dna")
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        rows = await list_snapshots(session, profile_id)
    return [SnapshotSummary(version=r["version"], taken_at=r["taken_at"]) for r in rows]


@profiles_router.get("/{person_id}/dna/snapshots/{version}", response_model=SnapshotDetail)
async def read_dna_snapshot(
    person_id: uuid.UUID,
    version: int,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> SnapshotDetail:
    """Read a specific DNA snapshot's full payload (consent-scoped)."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read_dna")
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        snap = await get_snapshot(session, profile_id, version)
    if snap is None:
        raise NotFound("Snapshot not found")
    return SnapshotDetail(
        version=snap["version"], taken_at=snap["taken_at"], payload=snap["payload"]
    )


@profiles_router.get("/{person_id}/progress", response_model=list[TrendPoint])
async def read_progress(
    person_id: uuid.UUID,
    trait_key: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
    period: Period = "monthly",
) -> list[TrendPoint]:
    """Period-scoped trend of one trait (weekly/monthly/yearly), consent-scoped."""
    await _require_read_access(deps, subject=person_id, principal=principal, purpose="read_dna")
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        rows = await trait_trend(session, profile_id=profile_id, trait_key=trait_key, period=period)
    return [
        TrendPoint(period_start=r["period_start"], value=r["value"], confidence=r["confidence"])
        for r in rows
    ]


# --- Personal baseline (M04 Step 5, AC-M04-05, FR-M04-06) --------------------


class ObserveMetricRequest(BaseModel):
    metric_key: str = Field(..., description="CIP-STD metric id, e.g. 'BM-01'")
    value: float


class BaselineView(BaseModel):
    """Personal baseline in the CIP-STD metric shape (served to M15)."""

    metric_key: str
    distribution: dict[str, Any]
    updated_at: datetime | None = None


@profiles_router.post("/{person_id}/baseline", response_model=BaselineView, status_code=201)
async def observe_metric(
    person_id: uuid.UUID,
    body: ObserveMetricRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_role(BASELINE_WRITER_ROLE))],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BaselineView:
    """Internal: the analysis pipeline records a metric observation.

    Appends the value to the player's personal baseline for that CIP-STD metric
    and returns the recomputed distribution. Only the metrics-writer service
    scope may write (M10 / physics pipeline).
    """
    _ = principal
    if not is_valid_metric_id(body.metric_key):
        raise BadRequest(
            "metric_key must be a CIP-STD metric id (e.g. 'BM-01')",
            details={"metric_key": body.metric_key},
        )
    profile_id = await _resolve_profile_id(deps, person_id)
    async with admin_session(deps.session_factory) as session:
        summary = await record_observation(
            session, profile_id=profile_id, metric_key=body.metric_key, value=body.value
        )
    return BaselineView(metric_key=body.metric_key, distribution=summary)


@profiles_router.get("/{person_id}/baseline", response_model=list[BaselineView])
async def list_personal_baselines(
    person_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[BaselineView]:
    """Internal read for M15: all personal baselines in the CIP-STD shape.

    Gated on the subject's active 'processing' consent (analysis-derived data,
    same rule as the M10 attribute path — AC-M04-02/06)."""
    _ = principal
    async with admin_session(deps.session_factory) as session:
        if not await has_active_consent(
            session, person_id=person_id, consent_type=CONSENT_PROCESSING
        ):
            raise Forbidden(
                "Subject has not consented to processing", details={"reason": "no_consent"}
            )
        profile = await get_profile_by_person(session, person_id)
        if profile is None:
            raise NotFound("Profile not found")
        rows = await list_baselines(session, profile["id"])
    return [BaselineView(**r) for r in rows]


@profiles_router.get("/{person_id}/baseline/{metric_key}", response_model=BaselineView)
async def read_personal_baseline(
    person_id: uuid.UUID,
    metric_key: str,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> BaselineView:
    """Internal read for M15: one metric's personal baseline (CIP-STD shape)."""
    _ = principal
    async with admin_session(deps.session_factory) as session:
        if not await has_active_consent(
            session, person_id=person_id, consent_type=CONSENT_PROCESSING
        ):
            raise Forbidden(
                "Subject has not consented to processing", details={"reason": "no_consent"}
            )
        profile = await get_profile_by_person(session, person_id)
        if profile is None:
            raise NotFound("Profile not found")
        baseline = await get_baseline(session, profile["id"], metric_key)
    if baseline is None:
        raise NotFound("Baseline not found for that metric")
    return BaselineView(**baseline)
