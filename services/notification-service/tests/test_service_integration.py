"""Notification service orchestration integration tests (M19 Step 5).

Exercises the wired send pipeline (map -> gate -> idempotent create ->
render -> dispatch -> record) against a real database. The TRANSACTIONAL
bypass-preference path is covered at the pure gate_send level
(test_gating.py) — billing.notification.requested (this build's only
TRANSACTIONAL type) has no resolvable recipient yet (Step 2's documented
gap), so it can't be driven end-to-end through send_notification.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from notification_service.domain.channels import (
    FakeEmailChannel,
    FakeInAppChannel,
    FakePushChannel,
)
from notification_service.domain.preferences_repo import upsert_preference
from notification_service.domain.retry import DEAD_LETTERED, MAX_DELIVERY_ATTEMPTS, SENT
from notification_service.service import retry_notification, send_notification

pytestmark = pytest.mark.integration


class _AlwaysFailingChannel:
    def __init__(self) -> None:
        self.attempts = 0

    async def send(self, *, recipient_ref: uuid.UUID, message: object) -> str:
        self.attempts += 1
        raise RuntimeError("provider unavailable")


async def _make_person(
    session_factory: async_sessionmaker,
    *,
    status: str = "active",
    dob_band: str | None = "adult",
) -> uuid.UUID:
    person_id = uuid.uuid4()
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO persons (id, email, status, dob_band) "
                "VALUES (:id, :email, :status, :dob_band)"
            ),
            {
                "id": person_id,
                "email": f"{person_id}@example.test",
                "status": status,
                "dob_band": dob_band,
            },
        )
    return person_id


async def _link_guardian(
    session_factory: async_sessionmaker, *, minor_id: uuid.UUID, guardian_id: uuid.UUID
) -> None:
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO guardianships (id, minor_person_id, guardian_person_id, verified) "
                "VALUES (:id, :minor, :guardian, true)"
            ),
            {"id": uuid.uuid4(), "minor": minor_id, "guardian": guardian_id},
        )


async def _opt_in(
    session_factory: async_sessionmaker,
    *,
    person_ref: uuid.UUID,
    channel: str,
    topic: str,
) -> None:
    async with admin_session(session_factory) as session:
        await upsert_preference(
            session,
            person_ref=person_ref,
            channel=channel,
            topic=topic,
            enabled=True,
            quiet_hours=None,
        )


class TestSendNotification:
    async def test_opted_in_recipient_gets_sent(self, session_factory: async_sessionmaker) -> None:
        person_id = await _make_person(session_factory)
        await _opt_in(session_factory, person_ref=person_id, channel="email", topic="report_ready")
        email = FakeEmailChannel()
        row = await send_notification(
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
        assert row is not None
        assert row["status"] == SENT
        assert len(email.sent) == 1

    async def test_no_preference_row_yields_no_send_and_no_row(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        email = FakeEmailChannel()
        row = await send_notification(
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
        assert row is None
        assert email.sent == []

    async def test_replaying_the_same_event_does_not_send_twice(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        await _opt_in(session_factory, person_ref=person_id, channel="email", topic="report_ready")
        email = FakeEmailChannel()
        event_ref = f"evt-{uuid.uuid4()}"
        payload = {"person_id": str(person_id)}
        first = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload=payload,
            event_ref=event_ref,
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        second = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload=payload,
            event_ref=event_ref,
            channel="email",
            email_channel=email,
            push_channel=FakePushChannel(),
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert first is not None
        assert second is not None
        assert first["id"] == second["id"]
        assert len(email.sent) == 1

    async def test_a_minor_is_redirected_to_their_verified_guardian(
        self, session_factory: async_sessionmaker
    ) -> None:
        minor_id = await _make_person(session_factory, status="pending_consent", dob_band="minor")
        guardian_id = await _make_person(session_factory)
        await _link_guardian(session_factory, minor_id=minor_id, guardian_id=guardian_id)
        await _opt_in(session_factory, person_ref=minor_id, channel="in_app", topic="report_ready")
        in_app = FakeInAppChannel()
        row = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(minor_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="in_app",
            email_channel=FakeEmailChannel(),
            push_channel=FakePushChannel(),
            in_app_channel=in_app,
            hour=12,
        )
        assert row is not None
        assert row["recipient_ref"] == guardian_id
        assert in_app.sent[0][0] == guardian_id

    async def test_a_minor_with_no_guardian_is_never_sent(
        self, session_factory: async_sessionmaker
    ) -> None:
        minor_id = await _make_person(session_factory, status="pending_consent", dob_band="minor")
        await _opt_in(session_factory, person_ref=minor_id, channel="in_app", topic="report_ready")
        in_app = FakeInAppChannel()
        row = await send_notification(
            session_factory=session_factory,
            topic="report.ready",
            payload={"person_id": str(minor_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="in_app",
            email_channel=FakeEmailChannel(),
            push_channel=FakePushChannel(),
            in_app_channel=in_app,
            hour=12,
        )
        assert row is None
        assert in_app.sent == []

    async def test_first_attempt_failing_is_failed_not_dead_lettered(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        await _opt_in(session_factory, person_ref=person_id, channel="push", topic="plan_updated")
        failing = _AlwaysFailingChannel()
        row = await send_notification(
            session_factory=session_factory,
            topic="plan.updated",
            payload={"person_id": str(person_id)},
            event_ref=f"evt-{uuid.uuid4()}",
            channel="push",
            email_channel=FakeEmailChannel(),
            push_channel=failing,  # type: ignore[arg-type]
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert row is not None
        assert row["status"] == "failed"
        assert failing.attempts == 1

    async def test_retrying_past_the_ceiling_dead_letters(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory)
        await _opt_in(session_factory, person_ref=person_id, channel="push", topic="plan_updated")
        failing = _AlwaysFailingChannel()
        payload = {"person_id": str(person_id)}

        # Attempt 1 (via send_notification -- creates the row).
        row = await send_notification(
            session_factory=session_factory,
            topic="plan.updated",
            payload=payload,
            event_ref=f"evt-{uuid.uuid4()}",
            channel="push",
            email_channel=FakeEmailChannel(),
            push_channel=failing,  # type: ignore[arg-type]
            in_app_channel=FakeInAppChannel(),
            hour=12,
        )
        assert row is not None
        assert row["status"] == "failed"

        # Attempts 2..MAX_DELIVERY_ATTEMPTS (a future retry worker's job,
        # exercised directly here).
        status = row["status"]
        for _ in range(MAX_DELIVERY_ATTEMPTS - 1):
            status = await retry_notification(
                session_factory=session_factory,
                notification_id=row["id"],
                recipient_ref=row["recipient_ref"],
                notification_type_key="plan_updated",
                channel="push",
                payload=payload,
                email_channel=FakeEmailChannel(),
                push_channel=failing,  # type: ignore[arg-type]
                in_app_channel=FakeInAppChannel(),
            )
        assert status == DEAD_LETTERED
        assert failing.attempts == MAX_DELIVERY_ATTEMPTS
