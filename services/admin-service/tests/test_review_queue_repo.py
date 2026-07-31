"""Integration tests for M20's own biomechanics review queue (M20 Step 6, FR-M20-06)."""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain import review_queue_repo
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


class TestUpsertPending:
    async def test_creates_a_pending_item(self, session_factory: async_sessionmaker) -> None:
        tenant_id = uuid.uuid4()
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            row = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="elbow_flexion out of range"
            )
        assert row["status"] == review_queue_repo.PENDING
        assert row["tenant_id"] == tenant_id
        assert row["stroke_ref"] == stroke_ref

    async def test_re_flagging_the_same_stroke_is_a_no_op(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_id = uuid.uuid4()
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            first = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="bat_speed out of range"
            )
        async with admin_session(session_factory) as s:
            second = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="bat_speed out of range"
            )
        assert first["id"] == second["id"]


class TestListAndResolve:
    async def test_pending_item_appears_in_the_pending_queue(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_id = uuid.uuid4()
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            created = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="hip_rotation out of range"
            )
        async with admin_session(session_factory) as s:
            pending = await review_queue_repo.list_items(s, status=review_queue_repo.PENDING)
        assert any(item["id"] == created["id"] for item in pending)

    async def test_resolved_item_leaves_the_pending_queue(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_id = uuid.uuid4()
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            created = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="knee_flexion out of range"
            )
        async with admin_session(session_factory) as s:
            resolved = await review_queue_repo.resolve_item(
                s,
                item_id=created["id"],
                reviewer=str(uuid.uuid4()),
                resolution_note="verified genuine outlier stroke",
            )
        assert resolved is not None
        assert resolved["status"] == review_queue_repo.RESOLVED
        assert resolved["resolution_note"] == "verified genuine outlier stroke"

        async with admin_session(session_factory) as s:
            pending = await review_queue_repo.list_items(s, status=review_queue_repo.PENDING)
        assert not any(item["id"] == created["id"] for item in pending)

    async def test_resolving_twice_returns_none(self, session_factory: async_sessionmaker) -> None:
        tenant_id = uuid.uuid4()
        stroke_ref = f"m10-{uuid.uuid4().hex[:10]}"
        async with admin_session(session_factory) as s:
            created = await review_queue_repo.upsert_pending(
                s, tenant_id=tenant_id, stroke_ref=stroke_ref, reason="double resolve test"
            )
        async with admin_session(session_factory) as s:
            await review_queue_repo.resolve_item(
                s, item_id=created["id"], reviewer=str(uuid.uuid4()), resolution_note=None
            )
        async with admin_session(session_factory) as s:
            second = await review_queue_repo.resolve_item(
                s, item_id=created["id"], reviewer=str(uuid.uuid4()), resolution_note=None
            )
        assert second is None

    async def test_resolving_unknown_item_returns_none(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            row = await review_queue_repo.resolve_item(
                s, item_id=uuid.uuid4(), reviewer=str(uuid.uuid4()), resolution_note=None
            )
        assert row is None
