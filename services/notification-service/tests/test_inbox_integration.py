"""Inbox / preference-update / provider-status service integration tests (M19 Step 6).

No test_routes.py / full HTTP+RBAC suite — matching this build's own
precedent (M14-M18's capstone steps never added one either, given the
standing Docker blocker on running the full stack locally). These
exercise service.py's Step 6 functions directly against a real database.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from notification_service.domain import delivery_attempts_repo, notifications_repo
from notification_service.service import (
    get_inbox,
    handle_provider_status,
    mark_notification_read,
    update_preference,
)

pytestmark = pytest.mark.integration


async def _make_in_app_notification(
    session_factory: async_sessionmaker, *, recipient_ref: uuid.UUID
) -> dict:
    async with admin_session(session_factory) as session:
        row = await notifications_repo.create_if_new(
            session,
            recipient_ref=recipient_ref,
            notification_type="report_ready",
            channel="in_app",
            event_ref=f"evt-{uuid.uuid4()}",
            idempotency_key=f"key-{uuid.uuid4()}",
        )
    assert row is not None
    return row


class TestGetInbox:
    async def test_lists_only_this_recipients_in_app_notifications(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = uuid.uuid4()
        other_person = uuid.uuid4()
        mine = await _make_in_app_notification(session_factory, recipient_ref=person_id)
        await _make_in_app_notification(session_factory, recipient_ref=other_person)

        inbox = await get_inbox(session_factory=session_factory, recipient_ref=person_id)
        assert [n["id"] for n in inbox] == [mine["id"]]

    async def test_empty_inbox_for_a_person_with_no_notifications(
        self, session_factory: async_sessionmaker
    ) -> None:
        inbox = await get_inbox(session_factory=session_factory, recipient_ref=uuid.uuid4())
        assert inbox == []


class TestMarkNotificationRead:
    async def test_marks_the_callers_own_notification_read(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = uuid.uuid4()
        notification = await _make_in_app_notification(session_factory, recipient_ref=person_id)
        marked = await mark_notification_read(
            session_factory=session_factory,
            notification_id=notification["id"],
            recipient_ref=person_id,
        )
        assert marked is True

        inbox = await get_inbox(session_factory=session_factory, recipient_ref=person_id)
        assert inbox[0]["read_at"] is not None

    async def test_marking_an_already_read_notification_again_is_idempotent(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = uuid.uuid4()
        notification = await _make_in_app_notification(session_factory, recipient_ref=person_id)
        await mark_notification_read(
            session_factory=session_factory,
            notification_id=notification["id"],
            recipient_ref=person_id,
        )
        marked_again = await mark_notification_read(
            session_factory=session_factory,
            notification_id=notification["id"],
            recipient_ref=person_id,
        )
        assert marked_again is True

    async def test_cannot_mark_someone_elses_notification_read(
        self, session_factory: async_sessionmaker
    ) -> None:
        owner = uuid.uuid4()
        notification = await _make_in_app_notification(session_factory, recipient_ref=owner)
        marked = await mark_notification_read(
            session_factory=session_factory,
            notification_id=notification["id"],
            recipient_ref=uuid.uuid4(),
        )
        assert marked is False

    async def test_unknown_notification_id_returns_false(
        self, session_factory: async_sessionmaker
    ) -> None:
        marked = await mark_notification_read(
            session_factory=session_factory,
            notification_id=uuid.uuid4(),
            recipient_ref=uuid.uuid4(),
        )
        assert marked is False


class TestUpdatePreference:
    async def test_creates_then_updates_a_preference(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = uuid.uuid4()
        first = await update_preference(
            session_factory=session_factory,
            person_ref=person_id,
            channel="email",
            topic="report_ready",
            enabled=True,
            quiet_hours=None,
        )
        assert first["enabled"] is True
        second = await update_preference(
            session_factory=session_factory,
            person_ref=person_id,
            channel="email",
            topic="report_ready",
            enabled=False,
            quiet_hours={"start_hour": 22, "end_hour": 7},
        )
        assert second["id"] == first["id"]
        assert second["enabled"] is False


class TestHandleProviderStatus:
    async def test_delivered_status_updates_the_notification(
        self, session_factory: async_sessionmaker
    ) -> None:
        notification = await _make_in_app_notification(session_factory, recipient_ref=uuid.uuid4())
        provider_ref = f"provider-{uuid.uuid4()}"
        async with admin_session(session_factory) as session:
            await delivery_attempts_repo.record_attempt(
                session,
                notification_id=notification["id"],
                attempt=1,
                status="success",
                provider_ref=provider_ref,
            )

        result = await handle_provider_status(
            session_factory=session_factory, provider_ref=provider_ref, delivered=True
        )
        assert result is not None
        assert result["status"] == "delivered"

    async def test_failed_status_marks_the_notification_failed(
        self, session_factory: async_sessionmaker
    ) -> None:
        notification = await _make_in_app_notification(session_factory, recipient_ref=uuid.uuid4())
        provider_ref = f"provider-{uuid.uuid4()}"
        async with admin_session(session_factory) as session:
            await delivery_attempts_repo.record_attempt(
                session,
                notification_id=notification["id"],
                attempt=1,
                status="success",
                provider_ref=provider_ref,
            )

        result = await handle_provider_status(
            session_factory=session_factory, provider_ref=provider_ref, delivered=False
        )
        assert result is not None
        assert result["status"] == "failed"

    async def test_unknown_provider_ref_returns_none(
        self, session_factory: async_sessionmaker
    ) -> None:
        result = await handle_provider_status(
            session_factory=session_factory,
            provider_ref=f"nope-{uuid.uuid4()}",
            delivered=True,
        )
        assert result is None
