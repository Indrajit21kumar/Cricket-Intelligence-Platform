"""Academy API routes — M18 §10 (M18 Step 7).

  GET  /v1/academy/{tenant_id}/roster                        list roster
  POST /v1/academy/{tenant_id}/assignments                   assign coach to player
  POST /v1/academy/{tenant_id}/sessions                      create/schedule a session
  POST /v1/academy/{tenant_id}/sessions/{session_id}/status  transition session status
  POST /v1/sessions/{session_id}/attendance                  record attendance
  GET  /v1/academy/{tenant_id}/analytics                     team analytics + fair leaderboard
  GET  /v1/academy/{tenant_id}/players/{player_id}/dashboard one player's dashboard
  POST /v1/reports/{report_ref}/share                        share a report, consent-gated

Roster/assignments are TENANT_ADMIN-gated; the rest are COACHING-gated
(share only needs authentication — the real gate is consent, not role).
Every route is RBAC-gated (Book 3 §5.1, deny by default); the dashboard
and share routes additionally re-check live M02 membership/consent on
every call (never a cached decision) — see :mod:`academy_service.service`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from academy_service import service
from academy_service.deps import Deps, get_deps
from cip_core import (
    AuthenticatedPrincipal,
    require_authenticated,
    require_role,
    require_tenant_id,
    roles,
)

academy_router = APIRouter(prefix="/v1/academy", tags=["academy"])
sessions_router = APIRouter(prefix="/v1/sessions", tags=["sessions"])
reports_router = APIRouter(prefix="/v1/reports", tags=["reports"])

_manage_roster = require_role(*roles.TENANT_ADMIN_ROLES)
_coaching = require_role(*roles.COACHING_ROLES)


class RosterEntryResponse(BaseModel):
    person_id: uuid.UUID
    display_name: str | None
    assigned_coaches: list[uuid.UUID]


@academy_router.get("/{tenant_id}/roster", response_model=list[RosterEntryResponse])
async def get_roster(
    tenant_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> list[RosterEntryResponse]:
    entries = await service.list_roster(
        session_factory=deps.session_factory, roster_source=deps.roster_source, tenant_id=tenant_id
    )
    return [RosterEntryResponse(**e.to_dict()) for e in entries]


class AssignmentRequest(BaseModel):
    coach_ref: uuid.UUID
    player_ref: uuid.UUID


@academy_router.post("/{tenant_id}/assignments", status_code=201)
async def post_assignment(
    tenant_id: uuid.UUID,
    body: AssignmentRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(_manage_roster)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    return await service.assign_coach(
        session_factory=deps.session_factory,
        roster_source=deps.roster_source,
        tenant_id=tenant_id,
        coach_ref=body.coach_ref,
        player_ref=body.player_ref,
        requested_by=principal.person_id,
    )


class SessionRequest(BaseModel):
    scheduled_at: datetime


@academy_router.post("/{tenant_id}/sessions", status_code=201)
async def post_session(
    tenant_id: uuid.UUID,
    body: SessionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    return await service.create_session(
        session_factory=deps.session_factory,
        tenant_id=tenant_id,
        coach_ref=principal.person_id,
        scheduled_at=body.scheduled_at,
        requested_by=principal.person_id,
    )


class SessionStatusRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=32)


@academy_router.post("/{tenant_id}/sessions/{session_id}/status")
async def post_session_status(
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    body: SessionStatusRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    return await service.transition_session_status(
        session_factory=deps.session_factory,
        tenant_id=tenant_id,
        session_id=session_id,
        new_status=body.status,
        requested_by=principal.person_id,
    )


class AttendanceRequest(BaseModel):
    tenant_id: uuid.UUID
    player_ref: uuid.UUID
    attended: bool
    analysis_ref: str | None = None


@sessions_router.post("/{session_id}/attendance", status_code=201)
async def post_attendance(
    session_id: uuid.UUID,
    body: AttendanceRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    return await service.record_attendance(
        session_factory=deps.session_factory,
        roster_source=deps.roster_source,
        tenant_id=body.tenant_id,
        session_id=session_id,
        player_ref=body.player_ref,
        attended=body.attended,
        analysis_ref=body.analysis_ref,
        requested_by=principal.person_id,
    )


@academy_router.get("/{tenant_id}/players/{player_id}/dashboard")
async def get_dashboard(
    tenant_id: uuid.UUID,
    player_id: uuid.UUID,
    principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    dashboard = await service.get_dashboard(
        session_factory=deps.session_factory,
        roster_source=deps.roster_source,
        report_score_source=deps.report_score_source,
        dna_trait_source=deps.dna_trait_source,
        active_plan_source=deps.active_plan_source,
        tenant_id=tenant_id,
        coach_ref=principal.person_id,
        player_ref=player_id,
    )
    return dashboard.to_dict()


@academy_router.get("/{tenant_id}/analytics")
async def get_analytics(
    tenant_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(_coaching)],
    deps: Annotated[Deps, Depends(get_deps)],
    skill_tier: Annotated[str | None, Query()] = None,
    age_band: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    return await service.get_analytics(
        roster_source=deps.roster_source,
        report_score_source=deps.report_score_source,
        player_insights_source=deps.player_insights_source,
        cohort_context_source=deps.cohort_context_source,
        leaderboard_opt_in_source=deps.leaderboard_opt_in_source,
        tenant_id=tenant_id,
        skill_tier=skill_tier,
        age_band=age_band,
    )


class ShareRequest(BaseModel):
    shared_with: str = Field(..., min_length=1)
    player_ref: uuid.UUID


@reports_router.post("/{report_ref}/share", status_code=201)
async def post_share(
    report_ref: str,
    body: ShareRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    return await service.share_report(
        session_factory=deps.session_factory,
        event_bus=deps.event_bus,
        tenant_id=tenant_id,
        report_ref=report_ref,
        shared_with=body.shared_with,
        player_ref=body.player_ref,
        requested_by=principal.person_id,
    )
