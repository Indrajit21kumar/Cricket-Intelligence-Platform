"""coach_assignments repository integration tests (M18 Step 7)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from academy_service.domain import assignments_repo
from cip_data.engine import tenant_session

pytestmark = pytest.mark.integration


class TestAssign:
    async def test_assign_creates_an_active_row(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            row = await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        assert row["active"] is True
        assert row["coach_ref"] == coach
        assert row["player_ref"] == player

    async def test_assign_is_idempotent_for_the_same_pair(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            first = await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            second = await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        assert first["id"] == second["id"]

    async def test_assign_reactivates_a_deactivated_row(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.deactivate(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            assert (
                await assignments_repo.is_assigned(
                    session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
                )
                is False
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            assert (
                await assignments_repo.is_assigned(
                    session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
                )
                is True
            )


class TestIsAssigned:
    async def test_unknown_pair_is_not_assigned(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            assert (
                await assignments_repo.is_assigned(
                    session, tenant_id=tenant_id, coach_ref=uuid.uuid4(), player_ref=uuid.uuid4()
                )
                is False
            )


class TestActiveAssignmentsByPlayer:
    async def test_groups_coaches_by_player(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        player = uuid.uuid4()
        coach_a, coach_b = uuid.uuid4(), uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach_a, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach_b, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            result = await assignments_repo.active_assignments_by_player(
                session, tenant_id=tenant_id
            )
        assert set(result[player]) == {coach_a, coach_b}

    async def test_deactivated_assignments_are_excluded(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach, player = uuid.uuid4(), uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.assign(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await assignments_repo.deactivate(
                session, tenant_id=tenant_id, coach_ref=coach, player_ref=player
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            result = await assignments_repo.active_assignments_by_player(
                session, tenant_id=tenant_id
            )
        assert player not in result
