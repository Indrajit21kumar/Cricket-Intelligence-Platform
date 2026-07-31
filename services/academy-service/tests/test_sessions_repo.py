"""academy_sessions / session_players repository integration tests (M18 Step 7)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from academy_service.domain import sessions_repo
from cip_data.engine import tenant_session

pytestmark = pytest.mark.integration


class TestCreateAndGetSession:
    async def test_create_then_get_round_trips(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        coach = uuid.uuid4()
        scheduled_at = datetime.now(UTC)
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            created = await sessions_repo.create_session(
                session, tenant_id=tenant_id, coach_ref=coach, scheduled_at=scheduled_at
            )
        assert created["status"] == "scheduled"
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            fetched = await sessions_repo.get_session(
                session, tenant_id=tenant_id, session_id=created["id"]
            )
        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["coach_ref"] == coach

    async def test_get_unknown_session_returns_none(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            assert (
                await sessions_repo.get_session(
                    session, tenant_id=tenant_id, session_id=uuid.uuid4()
                )
                is None
            )


class TestUpdateSessionStatus:
    async def test_status_is_updated(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            created = await sessions_repo.create_session(
                session, tenant_id=tenant_id, coach_ref=None, scheduled_at=datetime.now(UTC)
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await sessions_repo.update_session_status(
                session, tenant_id=tenant_id, session_id=created["id"], status="completed"
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            fetched = await sessions_repo.get_session(
                session, tenant_id=tenant_id, session_id=created["id"]
            )
        assert fetched is not None
        assert fetched["status"] == "completed"


class TestAttendance:
    async def test_record_then_list(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        player = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            created = await sessions_repo.create_session(
                session, tenant_id=tenant_id, coach_ref=None, scheduled_at=datetime.now(UTC)
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            recorded = await sessions_repo.record_attendance(
                session,
                tenant_id=tenant_id,
                session_id=created["id"],
                player_ref=player,
                attended=True,
                analysis_ref="report-abc",
            )
        assert recorded["attended"] is True
        assert recorded["analysis_ref"] == "report-abc"
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = await sessions_repo.list_attendance(
                session, tenant_id=tenant_id, session_id=created["id"]
            )
        assert [r["player_ref"] for r in rows] == [player]

    async def test_recording_again_updates_rather_than_duplicates(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        player = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            created = await sessions_repo.create_session(
                session, tenant_id=tenant_id, coach_ref=None, scheduled_at=datetime.now(UTC)
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await sessions_repo.record_attendance(
                session,
                tenant_id=tenant_id,
                session_id=created["id"],
                player_ref=player,
                attended=False,
                analysis_ref=None,
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await sessions_repo.record_attendance(
                session,
                tenant_id=tenant_id,
                session_id=created["id"],
                player_ref=player,
                attended=True,
                analysis_ref="report-xyz",
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = await sessions_repo.list_attendance(
                session, tenant_id=tenant_id, session_id=created["id"]
            )
        assert len(rows) == 1
        assert rows[0]["attended"] is True
        assert rows[0]["analysis_ref"] == "report-xyz"
