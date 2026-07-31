"""preferences repository integration tests (M19 Step 4)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from notification_service.domain import preferences_repo

pytestmark = pytest.mark.integration


class TestUpsertPreference:
    async def test_creates_a_new_preference(self, session_factory: async_sessionmaker) -> None:
        person = uuid.uuid4()
        async with admin_session(session_factory) as session:
            row = await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        assert row["enabled"] is True
        assert row["quiet_hours"] is None

    async def test_upsert_updates_rather_than_duplicates(
        self, session_factory: async_sessionmaker
    ) -> None:
        person = uuid.uuid4()
        async with admin_session(session_factory) as session:
            first = await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="push",
                topic="plan_updated",
                enabled=True,
                quiet_hours=None,
            )
        async with admin_session(session_factory) as session:
            second = await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="push",
                topic="plan_updated",
                enabled=False,
                quiet_hours={"start_hour": 22, "end_hour": 7},
            )
        assert first["id"] == second["id"]
        assert second["enabled"] is False
        assert second["quiet_hours"] == {"start_hour": 22, "end_hour": 7}


class TestGetPreference:
    async def test_unknown_preference_returns_none(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as session:
            row = await preferences_repo.get_preference(
                session, person_ref=uuid.uuid4(), channel="email", topic="report_ready"
            )
        assert row is None

    async def test_returns_the_matching_row(self, session_factory: async_sessionmaker) -> None:
        person = uuid.uuid4()
        async with admin_session(session_factory) as session:
            await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="in_app",
                topic="dna_updated",
                enabled=True,
                quiet_hours=None,
            )
        async with admin_session(session_factory) as session:
            row = await preferences_repo.get_preference(
                session, person_ref=person, channel="in_app", topic="dna_updated"
            )
        assert row is not None
        assert row["person_ref"] == person


class TestListPreferences:
    async def test_lists_every_preference_for_a_person(
        self, session_factory: async_sessionmaker
    ) -> None:
        person = uuid.uuid4()
        async with admin_session(session_factory) as session:
            await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        async with admin_session(session_factory) as session:
            await preferences_repo.upsert_preference(
                session,
                person_ref=person,
                channel="push",
                topic="plan_updated",
                enabled=False,
                quiet_hours=None,
            )
        async with admin_session(session_factory) as session:
            rows = await preferences_repo.list_preferences(session, person_ref=person)
        assert {(r["channel"], r["topic"]) for r in rows} == {
            ("email", "report_ready"),
            ("push", "plan_updated"),
        }

    async def test_other_persons_preferences_are_excluded(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_a, person_b = uuid.uuid4(), uuid.uuid4()
        async with admin_session(session_factory) as session:
            await preferences_repo.upsert_preference(
                session,
                person_ref=person_a,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        async with admin_session(session_factory) as session:
            rows = await preferences_repo.list_preferences(session, person_ref=person_b)
        assert rows == []
