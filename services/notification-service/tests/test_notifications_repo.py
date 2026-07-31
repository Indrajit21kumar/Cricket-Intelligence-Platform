"""notifications / delivery_attempts repository integration tests (M19 Step 5)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session
from notification_service.domain import delivery_attempts_repo, notifications_repo

pytestmark = pytest.mark.integration


class TestCreateIfNew:
    async def test_creates_a_pending_notification(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as session:
            row = await notifications_repo.create_if_new(
                session,
                recipient_ref=uuid.uuid4(),
                notification_type="report_ready",
                channel="email",
                event_ref="evt-1",
                idempotency_key=f"key-{uuid.uuid4()}",
            )
        assert row is not None
        assert row["status"] == "pending"

    async def test_a_repeated_idempotency_key_creates_nothing(
        self, session_factory: async_sessionmaker
    ) -> None:
        key = f"key-{uuid.uuid4()}"
        async with admin_session(session_factory) as session:
            first = await notifications_repo.create_if_new(
                session,
                recipient_ref=uuid.uuid4(),
                notification_type="report_ready",
                channel="email",
                event_ref="evt-2",
                idempotency_key=key,
            )
        async with admin_session(session_factory) as session:
            second = await notifications_repo.create_if_new(
                session,
                recipient_ref=uuid.uuid4(),
                notification_type="report_ready",
                channel="email",
                event_ref="evt-2-replayed",
                idempotency_key=key,
            )
        assert first is not None
        assert second is None


class TestUpdateStatusAndLookup:
    async def test_update_status_is_reflected_on_lookup(
        self, session_factory: async_sessionmaker
    ) -> None:
        key = f"key-{uuid.uuid4()}"
        async with admin_session(session_factory) as session:
            row = await notifications_repo.create_if_new(
                session,
                recipient_ref=uuid.uuid4(),
                notification_type="plan_updated",
                channel="push",
                event_ref="evt-3",
                idempotency_key=key,
            )
        assert row is not None
        async with admin_session(session_factory) as session:
            await notifications_repo.update_status(
                session, notification_id=row["id"], status="dead_lettered"
            )
        async with admin_session(session_factory) as session:
            fetched = await notifications_repo.get_by_idempotency_key(session, idempotency_key=key)
        assert fetched is not None
        assert fetched["status"] == "dead_lettered"

    async def test_unknown_key_returns_none(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as session:
            assert (
                await notifications_repo.get_by_idempotency_key(
                    session, idempotency_key=f"nope-{uuid.uuid4()}"
                )
                is None
            )


class TestDeliveryAttempts:
    async def test_record_then_count_then_list(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as session:
            notification = await notifications_repo.create_if_new(
                session,
                recipient_ref=uuid.uuid4(),
                notification_type="report_ready",
                channel="email",
                event_ref="evt-4",
                idempotency_key=f"key-{uuid.uuid4()}",
            )
        assert notification is not None
        notification_id = notification["id"]

        async with admin_session(session_factory) as session:
            await delivery_attempts_repo.record_attempt(
                session,
                notification_id=notification_id,
                attempt=1,
                status="failure",
                provider_ref=None,
            )
        async with admin_session(session_factory) as session:
            await delivery_attempts_repo.record_attempt(
                session,
                notification_id=notification_id,
                attempt=2,
                status="success",
                provider_ref="provider-ref-abc",
            )

        async with admin_session(session_factory) as session:
            count = await delivery_attempts_repo.count_attempts(
                session, notification_id=notification_id
            )
        assert count == 2

        async with admin_session(session_factory) as session:
            attempts = await delivery_attempts_repo.list_attempts(
                session, notification_id=notification_id
            )
        assert [a["attempt"] for a in attempts] == [1, 2]
        assert attempts[1]["provider_ref"] == "provider-ref-abc"
