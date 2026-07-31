"""Audit + opt-out integration tests (M19 Step 7, FR-M19-08, AC-M19-06).

TRANSACTIONAL delivery is exercised via retry_notification() directly
(passing a known recipient_ref/notification_type_key), not send_notification
-> billing.notification.requested (this build's only TRANSACTIONAL type)
has no resolvable recipient yet (Step 2's documented gap), so a
TRANSACTIONAL send can't be driven end-to-end through the event-mapping
entry point. retry_notification is a legitimate path here regardless of
that gap: it always took recipient/type as direct parameters, never
derived them from map_event.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from notification_service.domain import notifications_repo
from notification_service.domain.channels import FakeEmailChannel, FakeInAppChannel, FakePushChannel
from notification_service.domain.preferences_repo import upsert_preference
from notification_service.service import retry_notification, send_notification

pytestmark = pytest.mark.integration


async def _make_person(session_factory: async_sessionmaker) -> uuid.UUID:
    person_id = uuid.uuid4()
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO persons (id, email, status, dob_band) "
                "VALUES (:id, :email, 'active', 'adult')"
            ),
            {"id": person_id, "email": f"{person_id}@example.test"},
        )
    return person_id


async def _audit_rows_for(session_factory: async_sessionmaker, *, person_id: uuid.UUID) -> list:
    async with admin_session(session_factory) as session:
        rows = (
            await session.execute(
                text("SELECT action, entity FROM audit_log WHERE entity = :entity"),
                {"entity": f"person:{person_id}"},
            )
        ).all()
    return list(rows)


class TestTransactionalSendsAreAudited:
    async def test_a_transactional_delivery_writes_an_audit_row(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        async with admin_session(session_factory) as session:
            notification = await notifications_repo.create_if_new(
                session,
                recipient_ref=person_id,
                notification_type="billing.payment_failed",
                channel="push",
                event_ref=f"evt-{uuid.uuid4()}",
                idempotency_key=f"key-{uuid.uuid4()}",
            )
        assert notification is not None

        await retry_notification(
            session_factory=session_factory,
            notification_id=notification["id"],
            recipient_ref=person_id,
            notification_type_key="billing.payment_failed",
            channel="push",
            payload={"attempt_number": 1},
            email_channel=FakeEmailChannel(),
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
        )

        rows = await _audit_rows_for(session_factory, person_id=person_id)
        assert len(rows) == 1
        assert rows[0].action == "notification.sent"


class TestEngagementSendsAreNotAudited:
    async def test_an_engagement_delivery_writes_no_audit_row(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        async with admin_session(session_factory) as session:
            await upsert_preference(
                session,
                person_ref=person_id,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        row = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="email",
            email_channel=FakeEmailChannel(),
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert row is not None
        assert row["status"] == "sent"

        rows = await _audit_rows_for(session_factory, person_id=person_id)
        assert rows == []


class TestOptOutIsImmediate:
    async def test_a_second_distinct_event_after_opting_out_is_refused(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        async with admin_session(session_factory) as session:
            await upsert_preference(
                session,
                person_ref=person_id,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        email = FakeEmailChannel()

        first = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert first is not None
        assert first["status"] == "sent"

        async with admin_session(session_factory) as session:
            await upsert_preference(
                session,
                person_ref=person_id,
                channel="email",
                topic="report_ready",
                enabled=False,
                quiet_hours=None,
            )

        # A genuinely DIFFERENT event (different event_ref) for the same
        # person/topic/channel -- not a re-delivery of the first one.
        second = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert second is None
        assert len(email.sent) == 1  # only the first send ever reached the channel

    async def test_two_distinct_events_while_opted_in_both_send(
        self, session_factory: async_sessionmaker
    ) -> None:
        """Guards against the idempotency key colliding across distinct events."""
        person_id = await _make_person(session_factory)
        async with admin_session(session_factory) as session:
            await upsert_preference(
                session,
                person_ref=person_id,
                channel="email",
                topic="report_ready",
                enabled=True,
                quiet_hours=None,
            )
        email = FakeEmailChannel()

        first = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        second = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert first is not None
        assert second is not None
        assert first["id"] != second["id"]
        assert len(email.sent) == 2
