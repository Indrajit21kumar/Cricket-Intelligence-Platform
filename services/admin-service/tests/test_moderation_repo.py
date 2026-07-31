"""Integration tests for content moderation (M20 Step 3, FR-M20-02)."""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain import moderation_repo
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


class TestCreateAndListCases:
    async def test_created_case_appears_in_open_queue(
        self, session_factory: async_sessionmaker
    ) -> None:
        subject = f"video:{uuid.uuid4()}"
        async with admin_session(session_factory) as s:
            row = await moderation_repo.create_case(
                s, subject_ref=subject, reason="reported by user"
            )
        assert row["status"] == moderation_repo.OPEN
        async with admin_session(session_factory) as s:
            open_cases = await moderation_repo.list_cases(s, status=moderation_repo.OPEN)
        assert any(c["id"] == row["id"] for c in open_cases)


class TestResolveCase:
    async def test_actioned_case_leaves_the_open_queue(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            case = await moderation_repo.create_case(
                s, subject_ref=f"video:{uuid.uuid4()}", reason="flagged clip"
            )
        async with admin_session(session_factory) as s:
            resolved = await moderation_repo.resolve_case(
                s,
                case_id=case["id"],
                decision=moderation_repo.ACTIONED,
                actioned_by=str(uuid.uuid4()),
                action_taken="clip_removed",
            )
        assert resolved is not None
        assert resolved["status"] == moderation_repo.ACTIONED
        assert resolved["action"] == "clip_removed"

        async with admin_session(session_factory) as s:
            open_cases = await moderation_repo.list_cases(s, status=moderation_repo.OPEN)
        assert not any(c["id"] == case["id"] for c in open_cases)

    async def test_dismissed_case_records_decision(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            case = await moderation_repo.create_case(
                s, subject_ref=f"video:{uuid.uuid4()}", reason="unverified report"
            )
        async with admin_session(session_factory) as s:
            resolved = await moderation_repo.resolve_case(
                s,
                case_id=case["id"],
                decision=moderation_repo.DISMISSED,
                actioned_by=str(uuid.uuid4()),
            )
        assert resolved is not None
        assert resolved["status"] == moderation_repo.DISMISSED

    async def test_resolving_an_already_resolved_case_returns_none(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            case = await moderation_repo.create_case(
                s, subject_ref=f"video:{uuid.uuid4()}", reason="double resolve"
            )
        async with admin_session(session_factory) as s:
            await moderation_repo.resolve_case(
                s,
                case_id=case["id"],
                decision=moderation_repo.DISMISSED,
                actioned_by=str(uuid.uuid4()),
            )
        async with admin_session(session_factory) as s:
            second = await moderation_repo.resolve_case(
                s,
                case_id=case["id"],
                decision=moderation_repo.ACTIONED,
                actioned_by=str(uuid.uuid4()),
            )
        assert second is None

    async def test_resolving_unknown_case_returns_none(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            row = await moderation_repo.resolve_case(
                s,
                case_id=uuid.uuid4(),
                decision=moderation_repo.ACTIONED,
                actioned_by=str(uuid.uuid4()),
            )
        assert row is None
