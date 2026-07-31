"""cip_core.contactability / verified_guardians_of integration tests (M19 Step 4).

Exercises the two new cip-core consent helpers this step relies on, against
a real identity-service schema — no dedicated cip-core test file exists for
consent.py (its functions are tested from the consuming service's side
throughout this build, e.g. profile-service/academy-service), so this
module carries that coverage for notification-service's own dependency.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import contactability, verified_guardians_of
from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


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
    session_factory: async_sessionmaker,
    *,
    minor_id: uuid.UUID,
    guardian_id: uuid.UUID,
    verified: bool,
) -> None:
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO guardianships (id, minor_person_id, guardian_person_id, verified) "
                "VALUES (:id, :minor, :guardian, :verified)"
            ),
            {"id": uuid.uuid4(), "minor": minor_id, "guardian": guardian_id, "verified": verified},
        )


class TestContactability:
    async def test_active_adult_is_contactable_not_a_minor(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory, status="active", dob_band="adult")
        async with admin_session(session_factory) as session:
            info = await contactability(session, person_id=person_id)
        assert info.is_contactable is True
        assert info.is_minor is False

    async def test_pending_verification_is_not_contactable(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory, status="pending_verification")
        async with admin_session(session_factory) as session:
            info = await contactability(session, person_id=person_id)
        assert info.is_contactable is False

    async def test_minor_dob_band_is_flagged_as_minor(
        self, session_factory: async_sessionmaker
    ) -> None:
        person_id = await _make_person(session_factory, status="pending_consent", dob_band="minor")
        async with admin_session(session_factory) as session:
            info = await contactability(session, person_id=person_id)
        assert info.is_minor is True

    async def test_unknown_person_is_not_contactable(
        self, session_factory: async_sessionmaker
    ) -> None:
        async with admin_session(session_factory) as session:
            info = await contactability(session, person_id=uuid.uuid4())
        assert info.is_contactable is False
        assert info.is_minor is False


class TestVerifiedGuardiansOf:
    async def test_no_guardianship_returns_empty(self, session_factory: async_sessionmaker) -> None:
        minor_id = await _make_person(session_factory, dob_band="minor")
        async with admin_session(session_factory) as session:
            guardians = await verified_guardians_of(session, minor_person_id=minor_id)
        assert guardians == []

    async def test_returns_only_verified_guardians(
        self, session_factory: async_sessionmaker
    ) -> None:
        minor_id = await _make_person(session_factory, dob_band="minor")
        verified_guardian = await _make_person(session_factory)
        unverified_guardian = await _make_person(session_factory)
        await _link_guardian(
            session_factory, minor_id=minor_id, guardian_id=verified_guardian, verified=True
        )
        await _link_guardian(
            session_factory, minor_id=minor_id, guardian_id=unverified_guardian, verified=False
        )
        async with admin_session(session_factory) as session:
            guardians = await verified_guardians_of(session, minor_person_id=minor_id)
        assert guardians == [verified_guardian]
