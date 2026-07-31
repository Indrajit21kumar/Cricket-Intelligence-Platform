"""Access-control + portability + audit integration tests (M18 Step 7).

FR-M18-06/07, NFR-M18-02/03, AC-M18-02/06/07. Exercises
:func:`academy_service.service.get_dashboard` and
:func:`academy_service.service.assign_coach` against a real database —
the live ``coach_assignments`` read is what makes cross-tenant,
cross-coach, and portability enforcement structural rather than a policy
that could be forgotten in some other code path.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from academy_service import service
from academy_service.domain import assignments_repo
from academy_service.domain.sources import (
    FakeActivePlanSource,
    FakeDNATraitSource,
    FakeReportScoreSource,
    FakeRosterSource,
    RosterMember,
)
from cip_core.errors import Forbidden, NotFound
from cip_core.roles import PLAYER
from cip_data.engine import admin_session, tenant_session

pytestmark = pytest.mark.integration


def _sources() -> tuple[
    FakeRosterSource, FakeReportScoreSource, FakeDNATraitSource, FakeActivePlanSource
]:
    return (
        FakeRosterSource(),
        FakeReportScoreSource(),
        FakeDNATraitSource(),
        FakeActivePlanSource(),
    )


async def _second_tenant(session_factory: async_sessionmaker) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO tenants (id, name, type, region) VALUES (:id, :name, 'academy', 'IN')"
            ),
            {"id": tid, "name": f"acad-access-{uuid.uuid4().hex[:8]}"},
        )
    return tid


class TestGetDashboardAccessControl:
    async def test_assigned_coach_sees_a_current_members_dashboard(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        roster, scores, dna, plans = _sources()
        roster.set_members(
            tenant_id, [RosterMember(person_id=player, role=PLAYER, display_name="Kavya")]
        )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )

        dashboard = await service.get_dashboard(
            session_factory=session_factory,
            roster_source=roster,
            report_score_source=scores,
            dna_trait_source=dna,
            active_plan_source=plans,
            tenant_id=tenant_id,
            coach_ref=coach,
            player_ref=player,
        )
        assert dashboard.person_id == player
        assert dashboard.display_name == "Kavya"

    async def test_unassigned_coach_is_denied(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        roster, scores, dna, plans = _sources()
        roster.set_members(tenant_id, [RosterMember(person_id=player, role=PLAYER)])

        with pytest.raises(Forbidden):
            await service.get_dashboard(
                session_factory=session_factory,
                roster_source=roster,
                report_score_source=scores,
                dna_trait_source=dna,
                active_plan_source=plans,
                tenant_id=tenant_id,
                coach_ref=coach,
                player_ref=player,
            )

    async def test_a_different_coach_than_the_assigned_one_is_denied(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        assigned_coach, other_coach, player = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        roster, scores, dna, plans = _sources()
        roster.set_members(tenant_id, [RosterMember(person_id=player, role=PLAYER)])
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=assigned_coach, player_ref=player
            )

        with pytest.raises(Forbidden):
            await service.get_dashboard(
                session_factory=session_factory,
                roster_source=roster,
                report_score_source=scores,
                dna_trait_source=dna,
                active_plan_source=plans,
                tenant_id=tenant_id,
                coach_ref=other_coach,
                player_ref=player,
            )

    async def test_an_assignment_in_a_different_tenant_does_not_grant_access(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        other_tenant = await _second_tenant(session_factory)
        coach, player = uuid.uuid4(), uuid.uuid4()
        roster, scores, dna, plans = _sources()
        # The player is on the OTHER tenant's roster too, but the assignment
        # below only exists in `other_tenant`.
        roster.set_members(tenant_id, [RosterMember(person_id=player, role=PLAYER)])
        async with tenant_session(session_factory, tenant_id=other_tenant) as session:
            await assignments_repo.assign(
                session, tenant_id=other_tenant, coach_ref=coach, player_ref=player
            )

        with pytest.raises(Forbidden):
            await service.get_dashboard(
                session_factory=session_factory,
                roster_source=roster,
                report_score_source=scores,
                dna_trait_source=dna,
                active_plan_source=plans,
                tenant_id=tenant_id,
                coach_ref=coach,
                player_ref=player,
            )

    async def test_a_player_who_has_left_the_academy_is_no_longer_visible(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """Portability (FR-M18-07): the assignment row survives, but access doesn't."""
        coach, player = uuid.uuid4(), uuid.uuid4()
        roster, scores, dna, plans = _sources()
        # No roster membership set — simulates the player having left M02.
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
            assert (
                await assignments_repo.is_assigned(
                    session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
                )
                is True
            )

        with pytest.raises(Forbidden):
            await service.get_dashboard(
                session_factory=session_factory,
                roster_source=roster,
                report_score_source=scores,
                dna_trait_source=dna,
                active_plan_source=plans,
                tenant_id=tenant_id,
                coach_ref=coach,
                player_ref=player,
            )


class TestAuditTrail:
    async def test_assigning_a_coach_writes_an_audit_row(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player, admin = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        roster = FakeRosterSource()
        roster.set_members(tenant_id, [RosterMember(person_id=player, role=PLAYER)])

        await service.assign_coach(
            session_factory=session_factory,
            roster_source=roster,
            tenant_id=tenant_id,
            coach_ref=coach,
            player_ref=player,
            requested_by=admin,
        )

        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT actor, action, entity FROM audit_log "
                        "WHERE tenant_id = :tid AND action = 'coach.assigned' "
                        "ORDER BY at DESC LIMIT 1"
                    ),
                    {"tid": tenant_id},
                )
            ).first()
        assert row is not None
        assert row.actor == str(admin)
        assert row.entity == f"person:{player}"

    async def test_assigning_to_a_non_member_is_rejected(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        roster = FakeRosterSource()  # empty roster
        with pytest.raises(NotFound):
            await service.assign_coach(
                session_factory=session_factory,
                roster_source=roster,
                tenant_id=tenant_id,
                coach_ref=uuid.uuid4(),
                player_ref=uuid.uuid4(),
                requested_by=uuid.uuid4(),
            )
