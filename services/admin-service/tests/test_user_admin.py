"""Integration tests for user administration (M20 Step 3, FR-M20-01)."""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain import user_admin
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


async def _make_person(sf: async_sessionmaker, *, email: str, status: str = "active") -> uuid.UUID:
    pid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO persons (id, email, status) VALUES (:id, :email, :status)"),
            {"id": pid, "email": email, "status": status},
        )
    return pid


class TestSearchUsers:
    async def test_finds_by_email_substring(self, session_factory: async_sessionmaker) -> None:
        unique = uuid.uuid4().hex[:8]
        await _make_person(session_factory, email=f"{unique}@example.test")
        async with admin_session(session_factory) as s:
            results = await user_admin.search_users(s, query=unique)
        assert len(results) == 1
        assert results[0]["email"] == f"{unique}@example.test"

    async def test_no_query_returns_recent_users(self, session_factory: async_sessionmaker) -> None:
        await _make_person(session_factory, email=f"{uuid.uuid4().hex}@example.test")
        async with admin_session(session_factory) as s:
            results = await user_admin.search_users(s, query=None, limit=5)
        assert len(results) <= 5


class TestGetUser:
    async def test_returns_none_for_unknown_person(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as s:
            row = await user_admin.get_user(s, uuid.uuid4())
        assert row is None

    async def test_returns_the_person(self, session_factory: async_sessionmaker) -> None:
        pid = await _make_person(session_factory, email=f"{uuid.uuid4().hex}@example.test")
        async with admin_session(session_factory) as s:
            row = await user_admin.get_user(s, pid)
        assert row is not None
        assert row["id"] == pid


class TestSetUserStatus:
    async def test_suspend_then_restore(self, session_factory: async_sessionmaker) -> None:
        pid = await _make_person(session_factory, email=f"{uuid.uuid4().hex}@example.test")
        async with admin_session(session_factory) as s:
            suspended = await user_admin.set_user_status(s, pid, user_admin.SUSPENDED)
        assert suspended is not None
        assert suspended["status"] == user_admin.SUSPENDED

        async with admin_session(session_factory) as s:
            restored = await user_admin.set_user_status(s, pid, user_admin.ACTIVE)
        assert restored is not None
        assert restored["status"] == user_admin.ACTIVE

    async def test_unknown_person_returns_none(self, session_factory: async_sessionmaker) -> None:
        async with admin_session(session_factory) as s:
            row = await user_admin.set_user_status(s, uuid.uuid4(), user_admin.SUSPENDED)
        assert row is None
