"""Export, deletion, portability + consent withdrawal (M04 Step 6).

Covers AC-M04-01 (portability: leaving a tenant preserves the profile),
AC-M04-06 (withdrawal restricts access), FR-M04-09 (export/delete honoured +
audited).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text

from cip_core import roles
from cip_data.engine import admin_session, build_engine, build_session_factory
from profile_service.main import create_app
from profile_service.routes import DNA_WRITER_ROLE

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


@pytest_asyncio.fixture
async def client(_migrated_database: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


def _token(person_id: uuid.UUID, *claim_roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(person_id),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _auth(person_id: uuid.UUID, *claim_roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(person_id, *claim_roles)}"}


def _m16() -> dict[str, str]:
    return _auth(uuid.uuid4(), DNA_WRITER_ROLE)


async def _seed_person(db: str, *, dob_band: str | None = None) -> uuid.UUID:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    pid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text("INSERT INTO persons (id, email, dob_band) VALUES (:id, :e, :d)"),
                {"id": pid, "e": f"p-{pid.hex[:10]}@test", "d": dob_band},
            )
    finally:
        await engine.dispose()
    return pid


async def _tenant_with_member(db: str, *, person_id: uuid.UUID, role: str) -> uuid.UUID:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"
                ),
                {"id": tid, "n": f"acad-{tid.hex[:8]}"},
            )
            await s.execute(
                text(
                    "INSERT INTO memberships (id, person_id, tenant_id, role) "
                    "VALUES (:id, :p, :t, :r)"
                ),
                {"id": uuid.uuid4(), "p": person_id, "t": tid, "r": role},
            )
    finally:
        await engine.dispose()
    return tid


async def _add_member(db: str, *, person_id: uuid.UUID, tenant_id: uuid.UUID, role: str) -> None:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO memberships (id, person_id, tenant_id, role) "
                    "VALUES (:id, :p, :t, :r)"
                ),
                {"id": uuid.uuid4(), "p": person_id, "t": tenant_id, "r": role},
            )
    finally:
        await engine.dispose()


async def _leave_tenant(db: str, *, person_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Simulate M02 leave: mark the membership inactive."""
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "UPDATE memberships SET status = 'left' WHERE person_id = :p AND tenant_id = :t"
                ),
                {"p": person_id, "t": tenant_id},
            )
    finally:
        await engine.dispose()


async def _seed_consent(
    db: str, *, person_id: uuid.UUID, consent_type: str, tenant_id: uuid.UUID | None = None
) -> uuid.UUID:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    cid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO consents (id, person_id, tenant_id, type, granted_by, scope) "
                    "VALUES (:id, :p, :t, :ty, :p, '{}'::jsonb)"
                ),
                {"id": cid, "p": person_id, "t": tenant_id, "ty": consent_type},
            )
    finally:
        await engine.dispose()
    return cid


async def _withdraw_consent(db: str, consent_id: uuid.UUID) -> None:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text("UPDATE consents SET withdrawn_at = now() WHERE id = :id"),
                {"id": consent_id},
            )
    finally:
        await engine.dispose()


async def _seed_guardianship(db: str, *, minor: uuid.UUID, guardian: uuid.UUID) -> None:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO guardianships "
                    "  (id, minor_person_id, guardian_person_id, verified) "
                    "VALUES (:id, :m, :g, true)"
                ),
                {"id": uuid.uuid4(), "m": minor, "g": guardian},
            )
    finally:
        await engine.dispose()


async def _seed_person_with_profile(client: httpx.AsyncClient, db: str) -> uuid.UUID:
    pid = await _seed_person(db)
    r = await client.post(
        f"/v1/players/{pid}/profile",
        headers=_auth(pid, roles.PLAYER),
        json={"height_cm": 175},
    )
    assert r.status_code == 201, r.text
    return pid


async def _audit_count(db: str, action: str, person_id: uuid.UUID) -> int:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            row = await s.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE action = :a AND entity = :e AND tenant_id IS NULL"
                ),
                {"a": action, "e": f"person:{person_id}"},
            )
            return int(row.scalar() or 0)
    finally:
        await engine.dispose()


class TestExport:
    async def test_self_export_bundle(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16(),
            json={
                "updates": [{"trait_key": "trait.timing", "value": "0.7", "provenance": "modelled"}]
            },
        )
        r = await client.get(f"/v1/players/{pid}/export", headers=_auth(pid, roles.PLAYER))
        assert r.status_code == 200, r.text
        bundle = r.json()
        assert bundle["profile"]["height_cm"] == 175
        assert any(t["trait_key"] == "trait.timing" for t in bundle["dna_current"])
        # Export is audited (person-scoped -> tenant_id NULL).
        assert await _audit_count(_migrated_database, "profile.exported", pid) == 1

    async def test_coach_cannot_export_even_with_consent(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        tenant = await _tenant_with_member(_migrated_database, person_id=pid, role=roles.PLAYER)
        coach = await _seed_person(_migrated_database)
        await _add_member(_migrated_database, person_id=coach, tenant_id=tenant, role=roles.COACH)
        await _seed_consent(
            _migrated_database, person_id=pid, consent_type="sharing", tenant_id=tenant
        )
        # Coach can READ but must NOT be able to EXPORT.
        assert (
            await client.get(f"/v1/players/{pid}/profile", headers=_auth(coach, roles.COACH))
        ).status_code == 200
        r = await client.get(f"/v1/players/{pid}/export", headers=_auth(coach, roles.COACH))
        assert r.status_code == 403

    async def test_guardian_can_export_minor(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        minor = await _seed_person(_migrated_database, dob_band="minor")
        await client.post(
            f"/v1/players/{minor}/profile", headers=_auth(minor, roles.PLAYER), json={}
        )
        guardian = await _seed_person(_migrated_database)
        await _seed_guardianship(_migrated_database, minor=minor, guardian=guardian)
        r = await client.get(f"/v1/players/{minor}/export", headers=_auth(guardian, roles.PARENT))
        assert r.status_code == 200, r.text


class TestDelete:
    async def test_self_delete_cascades(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16(),
            json={
                "updates": [{"trait_key": "trait.power", "value": "0.5", "provenance": "modelled"}]
            },
        )
        d = await client.delete(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER))
        assert d.status_code == 200, d.text
        assert d.json()["deleted"] is True
        assert await _audit_count(_migrated_database, "profile.deleted", pid) == 1

        # Profile + DNA are gone.
        assert (
            await client.get(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER))
        ).status_code == 404
        assert (
            await client.get(f"/v1/players/{pid}/dna", headers=_auth(pid, roles.PLAYER))
        ).status_code == 404

    async def test_delete_missing_profile_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        r = await client.delete(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER))
        assert r.status_code == 404

    async def test_stranger_cannot_delete(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        stranger = await _seed_person(_migrated_database)
        r = await client.delete(
            f"/v1/players/{pid}/profile", headers=_auth(stranger, roles.ACADEMY_ADMIN)
        )
        assert r.status_code == 403


class TestPortability:
    async def test_leaving_tenant_preserves_profile_but_revokes_coach(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """AC-M04-01: the profile survives leaving a tenant; only access changes."""
        player = await _seed_person_with_profile(client, _migrated_database)
        tenant = await _tenant_with_member(_migrated_database, person_id=player, role=roles.PLAYER)
        coach = await _seed_person(_migrated_database)
        await _add_member(_migrated_database, person_id=coach, tenant_id=tenant, role=roles.COACH)
        await _seed_consent(
            _migrated_database, person_id=player, consent_type="sharing", tenant_id=tenant
        )

        # Coach can read while the player is a member.
        assert (
            await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        ).status_code == 200

        # Player leaves the tenant.
        await _leave_tenant(_migrated_database, person_id=player, tenant_id=tenant)

        # The profile itself is UNCHANGED and still readable by the player.
        self_read = await client.get(
            f"/v1/players/{player}/profile", headers=_auth(player, roles.PLAYER)
        )
        assert self_read.status_code == 200
        assert self_read.json()["height_cm"] == 175

        # But the coach has lost access (no active shared membership).
        assert (
            await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        ).status_code == 403


class TestConsentWithdrawal:
    async def test_withdrawing_sharing_consent_revokes_coach(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """AC-M04-06: withdrawal restricts access."""
        player = await _seed_person_with_profile(client, _migrated_database)
        tenant = await _tenant_with_member(_migrated_database, person_id=player, role=roles.PLAYER)
        coach = await _seed_person(_migrated_database)
        await _add_member(_migrated_database, person_id=coach, tenant_id=tenant, role=roles.COACH)
        cid = await _seed_consent(
            _migrated_database, person_id=player, consent_type="sharing", tenant_id=tenant
        )

        assert (
            await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        ).status_code == 200

        await _withdraw_consent(_migrated_database, cid)

        after = await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        assert after.status_code == 403
        assert after.json()["error"]["details"]["reason"] == "no_consent"
