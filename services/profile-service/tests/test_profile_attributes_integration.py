"""Attribute CRUD + consent-scoped access + M10 fast read (M04 Step 2).

Covers AC-M04-02 (M10 reads attributes fast; non-consented reader denied) and
the consent model: self always, guardian of a minor, coach only with sharing
consent + shared membership.
"""

from __future__ import annotations

import time
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


# --- seed helpers (write M02 rows directly; profile-service only reads them) --


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


async def _seed_tenant_and_membership(db: str, *, person_id: uuid.UUID, role: str) -> uuid.UUID:
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


async def _add_membership(
    db: str, *, person_id: uuid.UUID, tenant_id: uuid.UUID, role: str
) -> None:
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


async def _seed_consent(
    db: str,
    *,
    person_id: uuid.UUID,
    consent_type: str,
    granted_by: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
) -> None:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO consents (id, person_id, tenant_id, type, granted_by, scope) "
                    "VALUES (:id, :p, :t, :ty, :by, '{}'::jsonb)"
                ),
                {
                    "id": uuid.uuid4(),
                    "p": person_id,
                    "t": tenant_id,
                    "ty": consent_type,
                    "by": granted_by,
                },
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


class TestSelfAccess:
    async def test_self_create_and_read(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/profile",
            headers=_auth(pid, roles.PLAYER),
            json={"height_cm": 178, "stance": "right-hand-bat", "age_band": "senior"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["height_cm"] == 178

        got = await client.get(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER))
        assert got.status_code == 200
        assert got.json()["stance"] == "right-hand-bat"

    async def test_self_patch_attributes(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        await client.post(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={})

        r = await client.patch(
            f"/v1/players/{pid}/profile",
            headers=_auth(pid, roles.PLAYER),
            json={"height_cm": 180, "dominant_hand": "left"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["height_cm"] == 180
        assert r.json()["dominant_hand"] == "left"

    async def test_duplicate_create_conflicts(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        first = await client.post(
            f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={}
        )
        assert first.status_code == 201
        dup = await client.post(
            f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={}
        )
        assert dup.status_code == 409

    async def test_read_missing_profile_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        r = await client.get(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER))
        assert r.status_code == 404


class TestAuthAndAuthz:
    async def test_unauthenticated_401(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)
        r = await client.get(f"/v1/players/{pid}/profile")
        assert r.status_code == 401

    async def test_stranger_cannot_create_for_another(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        subject = await _seed_person(_migrated_database)
        stranger = await _seed_person(_migrated_database)
        r = await client.post(
            f"/v1/players/{subject}/profile",
            headers=_auth(stranger, roles.PLAYER),
            json={},
        )
        assert r.status_code == 403

    async def test_admin_can_create_for_another(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        subject = await _seed_person(_migrated_database)
        admin = await _seed_person(_migrated_database)
        r = await client.post(
            f"/v1/players/{subject}/profile",
            headers=_auth(admin, roles.ACADEMY_ADMIN),
            json={"height_cm": 165},
        )
        assert r.status_code == 201, r.text


class TestCoachConsent:
    async def test_coach_without_sharing_consent_denied(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        player = await _seed_person(_migrated_database)
        await client.post(
            f"/v1/players/{player}/profile", headers=_auth(player, roles.PLAYER), json={}
        )
        # Coach shares a tenant with the player but has NO sharing consent.
        tenant = await _seed_tenant_and_membership(
            _migrated_database, person_id=player, role=roles.PLAYER
        )
        coach = await _seed_person(_migrated_database)
        await _add_membership(
            _migrated_database, person_id=coach, tenant_id=tenant, role=roles.COACH
        )

        r = await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        assert r.status_code == 403
        assert r.json()["error"]["details"]["reason"] == "no_consent"

    async def test_coach_with_sharing_consent_allowed(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        player = await _seed_person(_migrated_database)
        await client.post(
            f"/v1/players/{player}/profile",
            headers=_auth(player, roles.PLAYER),
            json={"height_cm": 170},
        )
        tenant = await _seed_tenant_and_membership(
            _migrated_database, person_id=player, role=roles.PLAYER
        )
        coach = await _seed_person(_migrated_database)
        await _add_membership(
            _migrated_database, person_id=coach, tenant_id=tenant, role=roles.COACH
        )
        # Player grants a sharing consent scoped to that tenant.
        await _seed_consent(
            _migrated_database,
            person_id=player,
            consent_type="sharing",
            granted_by=player,
            tenant_id=tenant,
        )

        r = await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        assert r.status_code == 200, r.text
        assert r.json()["height_cm"] == 170

    async def test_coach_without_shared_tenant_denied(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        player = await _seed_person(_migrated_database)
        await client.post(
            f"/v1/players/{player}/profile", headers=_auth(player, roles.PLAYER), json={}
        )
        # Coach shares NO tenant with the player.
        coach = await _seed_person(_migrated_database)
        r = await client.get(f"/v1/players/{player}/profile", headers=_auth(coach, roles.COACH))
        assert r.status_code == 403
        assert r.json()["error"]["details"]["reason"] == "no_membership"


class TestGuardianAccess:
    async def test_guardian_reads_minor_profile(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        minor = await _seed_person(_migrated_database, dob_band="minor")
        guardian = await _seed_person(_migrated_database)
        await _seed_guardianship(_migrated_database, minor=minor, guardian=guardian)
        # Guardian creates + reads the minor's profile (guardian is not admin,
        # so create uses self/admin policy — seed the profile as the minor).
        await client.post(
            f"/v1/players/{minor}/profile",
            headers=_auth(minor, roles.PLAYER),
            json={"height_cm": 150},
        )

        r = await client.get(f"/v1/players/{minor}/profile", headers=_auth(guardian, roles.PARENT))
        assert r.status_code == 200, r.text
        assert r.json()["height_cm"] == 150


class TestM10FastAttributeRead:
    async def test_attributes_denied_without_processing_consent(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """AC-M04-02: a non-consented reader is denied on the fast path."""
        player = await _seed_person(_migrated_database)
        await client.post(
            f"/v1/players/{player}/profile",
            headers=_auth(player, roles.PLAYER),
            json={"height_cm": 172},
        )
        reader = await _seed_person(_migrated_database)
        r = await client.get(
            f"/v1/players/{player}/attributes", headers=_auth(reader, roles.PLAYER)
        )
        assert r.status_code == 403
        assert r.json()["error"]["details"]["reason"] == "no_consent"

    async def test_attributes_allowed_with_processing_consent_and_fast(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """AC-M04-02 + NFR-M04-01: consented read returns the attributes <50ms."""
        player = await _seed_person(_migrated_database)
        await client.post(
            f"/v1/players/{player}/profile",
            headers=_auth(player, roles.PLAYER),
            json={"height_cm": 175, "stance": "left-hand-bat", "age_band": "u19"},
        )
        await _seed_consent(
            _migrated_database,
            person_id=player,
            consent_type="processing",
            granted_by=player,
        )
        reader = await _seed_person(_migrated_database)
        headers = _auth(reader, roles.PLAYER)

        # Warm once, then measure — NFR is about the steady-state read path.
        await client.get(f"/v1/players/{player}/attributes", headers=headers)
        start = time.perf_counter()
        r = await client.get(f"/v1/players/{player}/attributes", headers=headers)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert r.status_code == 200, r.text
        assert r.json()["height_cm"] == 175
        assert r.json()["stance"] == "left-hand-bat"
        assert elapsed_ms < 50, f"attribute read took {elapsed_ms:.1f}ms (NFR-M04-01 <50ms)"

    async def test_attributes_missing_profile_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        player = await _seed_person(_migrated_database)
        await _seed_consent(
            _migrated_database,
            person_id=player,
            consent_type="processing",
            granted_by=player,
        )
        reader = await _seed_person(_migrated_database)
        r = await client.get(
            f"/v1/players/{player}/attributes", headers=_auth(reader, roles.PLAYER)
        )
        assert r.status_code == 404
