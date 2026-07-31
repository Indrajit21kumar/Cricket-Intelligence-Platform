"""Academy application service (M18 Step 7).

Where every prior step's pure domain logic meets I/O: persist through the
repos, enforce access control on every read that touches a specific
player, audit every institutional action, and publish the ``report.shared``
notification M19 will eventually consume.

Access control (FR-M18-06, NFR-M18-02, AC-M18-02) and portability
(FR-M18-07, AC-M18-06) are both grounded in
:func:`academy_service.domain.access.can_coach_view_player`: a fresh M02
roster read plus a fresh ``coach_assignments`` read, on every call — never
a cached decision. Cross-tenant and cross-coach access are blocked by the
same mechanism, not a separate check: an assignment row for a different
tenant or a different coach simply doesn't exist, so the read returns
nothing to compose a dashboard from.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from academy_service.domain import (
    assignments_repo,
    sessions_repo,
    shared_reports_repo,
)
from academy_service.domain.access import can_coach_view_player
from academy_service.domain.analytics import (
    LeaderboardCandidate,
    aggregate_strengths,
    aggregate_weak_areas,
    build_leaderboard,
    cohort_trend,
)
from academy_service.domain.dashboard import PlayerDashboard, compose_dashboard
from academy_service.domain.roster import RosterEntry, compose_roster, is_roster_member
from academy_service.domain.session import can_transition
from academy_service.domain.sharing import (
    COACH,
    NotificationIntent,
    build_notification_intent,
    evaluate_share,
    parse_recipient,
)
from academy_service.domain.sources import (
    ActivePlanSource,
    CohortContextSource,
    DNATraitSource,
    LeaderboardOptInSource,
    PlayerInsightsSource,
    ReportScoreSource,
    RosterSource,
)
from cip_core import (
    AccessDecision,
    Forbidden,
    NotFound,
    audit_record,
    check_profile_access,
    roles,
)
from cip_data import admin_session, tenant_session
from cip_events import EventBus, EventEnvelope

TOPIC_REPORT_SHARED = "report.shared"


async def list_roster(
    *, session_factory: async_sessionmaker[Any], roster_source: RosterSource, tenant_id: uuid.UUID
) -> list[RosterEntry]:
    """The academy's player roster with active coach assignments (FR-M18-01, AC-M18-01)."""
    members = await roster_source.load(tenant_id)
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        assignments = await assignments_repo.active_assignments_by_player(
            session, tenant_id=tenant_id
        )
    return compose_roster(members, assignments)


async def assign_coach(
    *,
    session_factory: async_sessionmaker[Any],
    roster_source: RosterSource,
    tenant_id: uuid.UUID,
    coach_ref: uuid.UUID,
    player_ref: uuid.UUID,
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    """Assign a coach to a player who is a current tenant member (FR-M18-01)."""
    members = await roster_source.load(tenant_id)
    if not is_roster_member(members, person_id=player_ref):
        raise NotFound("player is not a current member of this academy")
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await assignments_repo.assign(
            session, tenant_id=tenant_id, coach_ref=coach_ref, player_ref=player_ref
        )
        await _audit(
            session,
            action="coach.assigned",
            entity=f"person:{player_ref}",
            actor=str(requested_by),
            meta={"coach_ref": str(coach_ref)},
            tenant_id=tenant_id,
        )
    return row


async def create_session(
    *,
    session_factory: async_sessionmaker[Any],
    tenant_id: uuid.UUID,
    coach_ref: uuid.UUID | None,
    scheduled_at: datetime,
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    """Create/schedule a training session (FR-M18-02, AC-M18-03)."""
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await sessions_repo.create_session(
            session, tenant_id=tenant_id, coach_ref=coach_ref, scheduled_at=scheduled_at
        )
        await _audit(
            session,
            action="session.created",
            entity=f"session:{row['id']}",
            actor=str(requested_by),
            meta={"coach_ref": str(coach_ref) if coach_ref else None},
            tenant_id=tenant_id,
        )
    return row


async def transition_session_status(
    *,
    session_factory: async_sessionmaker[Any],
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    new_status: str,
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    """Move a session to COMPLETED/CANCELLED, enforcing Step 3's state machine."""
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        existing = await sessions_repo.get_session(
            session, tenant_id=tenant_id, session_id=session_id
        )
    if existing is None:
        raise NotFound("no such session in this academy")
    if not can_transition(existing["status"], new_status):
        raise Forbidden(f"cannot transition session from {existing['status']!r} to {new_status!r}")
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        await sessions_repo.update_session_status(
            session, tenant_id=tenant_id, session_id=session_id, status=new_status
        )
        await _audit(
            session,
            action="session.status_changed",
            entity=f"session:{session_id}",
            actor=str(requested_by),
            meta={"from": existing["status"], "to": new_status},
            tenant_id=tenant_id,
        )
    return {**existing, "status": new_status}


async def record_attendance(
    *,
    session_factory: async_sessionmaker[Any],
    roster_source: RosterSource,
    tenant_id: uuid.UUID,
    session_id: uuid.UUID,
    player_ref: uuid.UUID,
    attended: bool,
    analysis_ref: str | None,
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    """Record one player's attendance for a session (FR-M18-02, AC-M18-03)."""
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        existing = await sessions_repo.get_session(
            session, tenant_id=tenant_id, session_id=session_id
        )
    if existing is None:
        raise NotFound("no such session in this academy")
    members = await roster_source.load(tenant_id)
    if not is_roster_member(members, person_id=player_ref):
        raise NotFound("player is not a current member of this academy")
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await sessions_repo.record_attendance(
            session,
            tenant_id=tenant_id,
            session_id=session_id,
            player_ref=player_ref,
            attended=attended,
            analysis_ref=analysis_ref,
        )
        await _audit(
            session,
            action="attendance.recorded",
            entity=f"session:{session_id}",
            actor=str(requested_by),
            meta={"player_ref": str(player_ref), "attended": attended},
            tenant_id=tenant_id,
        )
    return row


async def get_dashboard(
    *,
    session_factory: async_sessionmaker[Any],
    roster_source: RosterSource,
    report_score_source: ReportScoreSource,
    dna_trait_source: DNATraitSource,
    active_plan_source: ActivePlanSource,
    tenant_id: uuid.UUID,
    coach_ref: uuid.UUID,
    player_ref: uuid.UUID,
) -> PlayerDashboard:
    """One player's dashboard, gated by live assignment + roster membership (AC-M18-04).

    Raises :class:`Forbidden` for an unassigned coach, a coach in the wrong
    tenant, or a player who has since left the academy — the same check
    covers all three (FR-M18-06, FR-M18-07, AC-M18-02/06).
    """
    members = await roster_source.load(tenant_id)
    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        assigned = await assignments_repo.is_assigned(
            session, tenant_id=tenant_id, coach_ref=coach_ref, player_ref=player_ref
        )
    if not can_coach_view_player(roster=members, player_id=player_ref, is_assigned=assigned):
        raise Forbidden("this player is not visible to this coach")

    display_name = next(
        (m.display_name for m in members if m.person_id == player_ref),
        None,
    )
    person_id_str = str(player_ref)
    scores = await report_score_source.load(person_id_str)
    dna_traits = await dna_trait_source.load(person_id_str)
    active_plan = await active_plan_source.load(person_id_str)
    return compose_dashboard(
        person_id=player_ref,
        display_name=display_name,
        scores=scores,
        dna_traits=dna_traits,
        active_plan=active_plan,
    )


async def get_analytics(
    *,
    roster_source: RosterSource,
    report_score_source: ReportScoreSource,
    player_insights_source: PlayerInsightsSource,
    cohort_context_source: CohortContextSource,
    leaderboard_opt_in_source: LeaderboardOptInSource,
    tenant_id: uuid.UUID,
    skill_tier: str | None,
    age_band: str | None,
) -> dict[str, Any]:
    """Team analytics + a fair, opt-in leaderboard for one cohort (AC-M18-05)."""
    roster = compose_roster(await roster_source.load(tenant_id), {})

    scores_by_player: dict[uuid.UUID, dict[str, Any] | None] = {}
    insights_by_player: dict[uuid.UUID, dict[str, Any]] = {}
    candidates: list[LeaderboardCandidate] = []
    for entry in roster:
        person_id_str = str(entry.person_id)
        scores = await report_score_source.load(person_id_str)
        scores_by_player[entry.person_id] = dict(scores) if scores is not None else None
        insights = await player_insights_source.load(person_id_str)
        insights_by_player[entry.person_id] = dict(insights)

        context = await cohort_context_source.load(person_id_str)
        opted_in = await leaderboard_opt_in_source.load(person_id_str)
        overall = scores.get("overall") if scores is not None else None
        overall_value = overall.get("value") if isinstance(overall, dict) else None
        if isinstance(overall_value, int | float):
            candidates.append(
                LeaderboardCandidate(
                    person_id=entry.person_id,
                    display_name=entry.display_name,
                    score=float(overall_value),
                    skill_tier=context.skill_tier,
                    age_band=context.age_band,
                    opted_in=opted_in,
                )
            )

    trend = cohort_trend(scores_by_player)
    leaderboard = build_leaderboard(candidates, skill_tier=skill_tier, age_band=age_band)
    return {
        "cohort_trend": trend.to_dict(),
        "weak_areas": [c.to_dict() for c in aggregate_weak_areas(insights_by_player)],
        "strengths": [c.to_dict() for c in aggregate_strengths(insights_by_player)],
        "leaderboard": [e.to_dict() for e in leaderboard],
    }


async def share_report(
    *,
    session_factory: async_sessionmaker[Any],
    event_bus: EventBus,
    tenant_id: uuid.UUID,
    report_ref: str,
    shared_with: str,
    player_ref: uuid.UUID,
    requested_by: uuid.UUID,
) -> dict[str, Any]:
    """Share a report with a guardian or coach, gated by M02 consent (FR-M18-05, AC-M18-07)."""
    recipient = parse_recipient(shared_with)
    reader_roles: tuple[str, ...] = (roles.COACH,) if recipient.kind == COACH else ()

    async with admin_session(session_factory) as session:
        access: AccessDecision = await check_profile_access(
            session,
            subject_person_id=player_ref,
            reader_person_id=recipient.recipient_id,
            reader_roles=reader_roles,
            purpose="report_share",
        )

    is_assigned_coach = False
    if recipient.kind == COACH:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            is_assigned_coach = await assignments_repo.is_assigned(
                session,
                tenant_id=tenant_id,
                coach_ref=recipient.recipient_id,
                player_ref=player_ref,
            )

    decision = evaluate_share(
        recipient=recipient, access=access, is_assigned_coach=is_assigned_coach
    )
    if not decision.allowed:
        raise Forbidden("report sharing is not consented", details={"reason": decision.reason})

    async with tenant_session(session_factory, tenant_id=tenant_id) as session:
        row = await shared_reports_repo.insert_share(
            session,
            tenant_id=tenant_id,
            report_ref=report_ref,
            shared_with=shared_with,
            shared_by=requested_by,
        )
        await _audit(
            session,
            action="report.shared",
            entity=f"person:{player_ref}",
            actor=str(requested_by),
            meta={"report_ref": report_ref, "shared_with": shared_with, "reason": decision.reason},
            tenant_id=tenant_id,
        )

    intent: NotificationIntent = build_notification_intent(
        tenant_id=tenant_id, player_ref=player_ref, recipient=recipient, report_ref=report_ref
    )
    envelope = EventEnvelope(
        correlation_id=report_ref,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=f"report.shared:{row['id']}",
        payload=intent.to_dict(),
    )
    await event_bus.publish(TOPIC_REPORT_SHARED, envelope)
    return row


async def _audit(
    session: AsyncSession,
    *,
    action: str,
    entity: str,
    actor: str,
    meta: dict[str, Any],
    tenant_id: uuid.UUID,
) -> None:
    await audit_record(
        session,
        action=action,
        entity=entity,
        actor=actor,
        meta=meta,
        tenant_id=tenant_id,
    )
