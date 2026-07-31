"""Admin console routes (M20 Step 2 onward, FR-M20-01, NFR-M20-01).

Every route here is gated by ``require_admin`` — deny-by-default, only
``platform_admin`` reaches anything under ``/v1/admin``. Step 2 established
this dependency once via ``whoami``; Step 3 adds the first real privileged
actions (user/tenant administration, content moderation), each recorded via
``record_admin_action`` exactly once.

Reads are never audited (harmless); every write is, since an admin's every
action is inherently cross-tenant/privileged (NFR-M20-02, FR-M20-09).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from admin_service.deps import Deps, get_deps
from admin_service.domain import (
    analytics,
    model_metrics_repo,
    moderation_repo,
    review_queue_repo,
    tenant_admin,
    user_admin,
)
from admin_service.domain.audit import record_admin_action
from cip_core import AuthenticatedPrincipal, NotFound, require_role, roles
from cip_data import admin_session

admin_router = APIRouter(prefix="/v1/admin", tags=["admin"])

#: The single RBAC gate every admin route depends on (deny-by-default).
require_admin = require_role(roles.PLATFORM_ADMIN)

#: Past-tense audit-action verb per suspend/restore action — NOT string
#: concatenation ("restore" + "ed" would wrongly read "restoreed").
_PAST_TENSE = {"suspend": "suspended", "restore": "restored"}


class WhoAmIResponse(BaseModel):
    person_id: str
    roles: list[str]


@admin_router.get("/whoami", response_model=WhoAmIResponse)
async def whoami(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
) -> WhoAmIResponse:
    """The caller's own identity — a harmless read, so not itself audited."""
    return WhoAmIResponse(person_id=str(principal.person_id), roles=list(principal.roles))


# --- Users (FR-M20-01) -------------------------------------------------------


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    status: str
    dob_band: str | None
    display_name: str | None
    created_at: datetime


class UserActionRequest(BaseModel):
    action: Literal["suspend", "restore"]
    reason: str | None = None


def _user_response(row: dict[str, Any]) -> UserResponse:
    return UserResponse(**row)


@admin_router.get("/users", response_model=list[UserResponse])
async def search_users(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
    q: str | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[UserResponse]:
    async with admin_session(deps.session_factory) as session:
        rows = await user_admin.search_users(session, query=q, limit=limit, offset=offset)
    return [_user_response(r) for r in rows]


@admin_router.get("/users/{person_id}", response_model=UserResponse)
async def get_user(
    person_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> UserResponse:
    async with admin_session(deps.session_factory) as session:
        row = await user_admin.get_user(session, person_id)
    if row is None:
        raise NotFound("user not found")
    return _user_response(row)


@admin_router.post("/users/{person_id}/action", response_model=UserResponse)
async def action_user(
    person_id: uuid.UUID,
    body: UserActionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> UserResponse:
    new_status = user_admin.ACTIVE if body.action == "restore" else user_admin.SUSPENDED
    async with admin_session(deps.session_factory) as session:
        row = await user_admin.set_user_status(session, person_id, new_status)
        if row is None:
            raise NotFound("user not found")
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action=f"user.{_PAST_TENSE[body.action]}",
            target=f"person:{person_id}",
            cross_tenant=True,
            meta={"reason": body.reason} if body.reason else None,
        )
    return _user_response(row)


# --- Tenants (FR-M20-01) ------------------------------------------------------


class TenantResponse(BaseModel):
    id: uuid.UUID
    name: str
    type: str | None
    region: str | None
    status: str
    created_at: datetime


class TenantActionRequest(BaseModel):
    action: Literal["suspend", "restore"]
    reason: str | None = None


@admin_router.get("/tenants/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> TenantResponse:
    async with admin_session(deps.session_factory) as session:
        row = await tenant_admin.get_tenant(session, tenant_id)
    if row is None:
        raise NotFound("tenant not found")
    return TenantResponse(**row)


@admin_router.post("/tenants/{tenant_id}/action", response_model=TenantResponse)
async def action_tenant(
    tenant_id: uuid.UUID,
    body: TenantActionRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> TenantResponse:
    new_status = tenant_admin.ACTIVE if body.action == "restore" else tenant_admin.SUSPENDED
    async with admin_session(deps.session_factory) as session:
        row = await tenant_admin.set_tenant_status(session, tenant_id, new_status)
        if row is None:
            raise NotFound("tenant not found")
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action=f"tenant.{_PAST_TENSE[body.action]}",
            target=f"tenant:{tenant_id}",
            tenant_ref=tenant_id,
            cross_tenant=True,
            meta={"reason": body.reason} if body.reason else None,
        )
    return TenantResponse(**row)


# --- Content moderation (FR-M20-02) -------------------------------------------


class ModerationCaseResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID | None
    subject_ref: str
    reason: str
    status: str
    action: str | None
    actioned_by: str | None
    actioned_at: datetime | None
    created_at: datetime


class ModerationCaseCreateRequest(BaseModel):
    subject_ref: str
    reason: str
    tenant_id: uuid.UUID | None = None


class ModerationResolveRequest(BaseModel):
    decision: Literal["actioned", "dismissed"]
    action_taken: str | None = None


@admin_router.get("/moderation", response_model=list[ModerationCaseResponse])
async def list_moderation_cases(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
    status: Literal["open", "actioned", "dismissed"] = "open",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ModerationCaseResponse]:
    async with admin_session(deps.session_factory) as session:
        rows = await moderation_repo.list_cases(session, status=status, limit=limit, offset=offset)
    return [ModerationCaseResponse(**r) for r in rows]


@admin_router.post("/moderation", response_model=ModerationCaseResponse, status_code=201)
async def create_moderation_case(
    body: ModerationCaseCreateRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ModerationCaseResponse:
    async with admin_session(deps.session_factory) as session:
        row = await moderation_repo.create_case(
            session, subject_ref=body.subject_ref, reason=body.reason, tenant_id=body.tenant_id
        )
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action="moderation.flagged",
            target=f"case:{row['id']}",
            tenant_ref=body.tenant_id,
            cross_tenant=True,
            meta={"subject_ref": body.subject_ref},
        )
    return ModerationCaseResponse(**row)


@admin_router.post("/moderation/{case_id}/resolve", response_model=ModerationCaseResponse)
async def resolve_moderation_case(
    case_id: uuid.UUID,
    body: ModerationResolveRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ModerationCaseResponse:
    async with admin_session(deps.session_factory) as session:
        row = await moderation_repo.resolve_case(
            session,
            case_id=case_id,
            decision=body.decision,
            actioned_by=str(principal.person_id),
            action_taken=body.action_taken,
        )
        if row is None:
            raise NotFound("moderation case not found, or already resolved")
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action=f"moderation.{body.decision}",
            target=f"case:{case_id}",
            tenant_ref=row["tenant_id"],
            cross_tenant=True,
            meta={"action_taken": body.action_taken} if body.action_taken else None,
        )
    return ModerationCaseResponse(**row)


# --- Revenue + usage analytics (FR-M20-03/04) ---------------------------------


class RevenueAnalyticsResponse(BaseModel):
    revenue_minor_by_currency: dict[str, int]
    invoice_count: int
    new_subscriptions: int
    cancellations: int
    upgrades: int
    downgrades: int
    churn_rate: float | None


class UsageAnalyticsResponse(BaseModel):
    analyses_started: int
    analyses_completed: int
    active_tenants: int
    active_players: int
    events_by_topic: dict[str, int]


class AnalyticsResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    revenue: RevenueAnalyticsResponse
    usage: UsageAnalyticsResponse


def _start_of_month(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@admin_router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
    period_start: datetime | None = None,
    period_end: datetime | None = None,
) -> AnalyticsResponse:
    """Revenue + usage analytics over the warehouse (NFR-M20-03: never the
    production DB) for one period. Defaults to the current calendar month
    to date — a live "this month so far" view."""
    now = datetime.now(UTC)
    start = period_start or _start_of_month(now)
    end = period_end or now
    async with admin_session(deps.session_factory) as session:
        revenue = await analytics.revenue_analytics(session, period_start=start, period_end=end)
        usage = await analytics.usage_analytics(session, period_start=start, period_end=end)
    return AnalyticsResponse(
        period_start=start,
        period_end=end,
        revenue=RevenueAnalyticsResponse(
            revenue_minor_by_currency=revenue.revenue_minor_by_currency,
            invoice_count=revenue.invoice_count,
            new_subscriptions=revenue.new_subscriptions,
            cancellations=revenue.cancellations,
            upgrades=revenue.upgrades,
            downgrades=revenue.downgrades,
            churn_rate=revenue.churn_rate,
        ),
        usage=UsageAnalyticsResponse(
            analyses_started=usage.analyses_started,
            analyses_completed=usage.analyses_completed,
            active_tenants=usage.active_tenants,
            active_players=usage.active_players,
            events_by_topic=usage.events_by_topic,
        ),
    )


# --- Model oversight (FR-M20-05) ----------------------------------------------


class ModelHealthResponse(BaseModel):
    model_name: str
    sample_count: int
    latest_accuracy: float | None
    latest_accuracy_at: datetime | None
    accuracy_trend: list[tuple[datetime, float]]
    drift: float | None
    confidence_mean: float | None
    confidence_mean_at: datetime | None


@admin_router.get("/models", response_model=list[ModelHealthResponse])
async def get_model_health(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
    since: datetime | None = None,
) -> list[ModelHealthResponse]:
    """Per-model accuracy-vs-golden trend, drift, and confidence calibration.

    Defaults to the trailing 30 days. A model with no telemetry yet reports
    honestly empty fields (None/[]) rather than a fabricated number — see
    :mod:`admin_service.domain.model_metrics_repo`.
    """
    window_start = since or (datetime.now(UTC) - timedelta(days=30))
    async with admin_session(deps.session_factory) as session:
        results = [
            await model_metrics_repo.model_health(session, model_name=name, since=window_start)
            for name in model_metrics_repo.KNOWN_MODELS
        ]
    return [
        ModelHealthResponse(
            model_name=r.model_name,
            sample_count=r.sample_count,
            latest_accuracy=r.latest_accuracy,
            latest_accuracy_at=r.latest_accuracy_at,
            accuracy_trend=r.accuracy_trend,
            drift=r.drift,
            confidence_mean=r.confidence_mean,
            confidence_mean_at=r.confidence_mean_at,
        )
        for r in results
    ]


# --- Biomechanics review queue (FR-M20-06) ------------------------------------


class ReviewQueueItemResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    stroke_ref: str
    reason: str
    status: str
    reviewer: str | None
    resolution_note: str | None
    resolved_at: datetime | None
    created_at: datetime


class ReviewQueueResolveRequest(BaseModel):
    resolution_note: str | None = None


@admin_router.get("/review-queue", response_model=list[ReviewQueueItemResponse])
async def list_review_queue(
    _principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
    status: Literal["pending", "resolved"] = "pending",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReviewQueueItemResponse]:
    async with admin_session(deps.session_factory) as session:
        rows = await review_queue_repo.list_items(
            session, status=status, limit=limit, offset=offset
        )
    return [ReviewQueueItemResponse(**r) for r in rows]


@admin_router.post("/review-queue/sync", response_model=dict[str, int])
async def sync_review_queue(
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, int]:
    """Pull every out-of-range, not-yet-reviewed stroke into M20's own queue."""
    pending = await deps.biomechanics_review_source.list_pending()
    async with admin_session(deps.session_factory) as session:
        for item in pending:
            await review_queue_repo.upsert_pending(
                session, tenant_id=item.tenant_id, stroke_ref=item.stroke_ref, reason=item.reason
            )
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action="review_queue.synced",
            target="review_queue",
            cross_tenant=True,
            meta={"synced_count": len(pending)},
        )
    return {"synced": len(pending)}


@admin_router.post("/review-queue/{item_id}/resolve", response_model=ReviewQueueItemResponse)
async def resolve_review_item(
    item_id: uuid.UUID,
    body: ReviewQueueResolveRequest,
    principal: Annotated[AuthenticatedPrincipal, Depends(require_admin)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> ReviewQueueItemResponse:
    async with admin_session(deps.session_factory) as session:
        row = await review_queue_repo.resolve_item(
            session,
            item_id=item_id,
            reviewer=str(principal.person_id),
            resolution_note=body.resolution_note,
        )
        if row is None:
            raise NotFound("review-queue item not found, or already resolved")
        await record_admin_action(
            session,
            admin_ref=str(principal.person_id),
            action="review_queue.resolved",
            target=f"review_queue_item:{item_id}",
            tenant_ref=row["tenant_id"],
            cross_tenant=True,
            meta={"resolution_note": body.resolution_note} if body.resolution_note else None,
        )
    # Close the loop with biomechanics-service (the same Fake seam Step 6's
    # domain module documents -- no real cross-service call exists yet).
    await deps.biomechanics_review_source.mark_reviewed(
        tenant_id=row["tenant_id"], stroke_ref=row["stroke_ref"]
    )
    return ReviewQueueItemResponse(**row)
