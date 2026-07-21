"""Membership + /v1/me integration tests (M02 Step 5 / AC-M02-03).

The headline test proves ENG-002 (persistent identity): a person can join
a tenant, leave it, and their persons row + credentials + subsequent
logins still work.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from cip_core import roles
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head
from identity_service.main import create_app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    _ = migrated_db
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


@pytest_asyncio.fixture
async def tenant_id(migrated_db: str) -> uuid.UUID:
    """Create a fresh tenant, return its id. Cleanup left to test isolation."""
    engine = build_engine(migrated_db)
    session_factory = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(session_factory) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) "
                    "VALUES (:id, :name, 'academy', 'IN')"
                ),
                {"id": tid, "name": f"acad-{uuid.uuid4().hex[:8]}"},
            )
        yield tid
    finally:
        await engine.dispose()


async def _register_and_login(client: httpx.AsyncClient) -> dict:
    """Full register->verify->login. Returns login response body + email/password."""
    email = f"user-{uuid.uuid4().hex[:8]}@fake-cricket.io"
    password = "long-password-for-tests-1234"
    reg = await client.post(
        "/v1/auth/register",
        headers={"Idempotency-Key": f"idem-{uuid.uuid4().hex}"},
        json={"email": email, "password": password, "dob": "1990-01-01"},
    )
    await client.post(
        "/v1/auth/verify-email",
        json={"token": reg.json()["verification_url_hint"]},
    )
    login = await client.post("/v1/auth/login", json={"email": email, "password": password})
    body = login.json()
    body["email"] = email
    body["password"] = password
    return body


class TestJoinTenant:
    async def test_join_and_visible_in_me(
        self, client: httpx.AsyncClient, tenant_id: uuid.UUID
    ) -> None:
        session = await _register_and_login(client)

        join = await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {session['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": roles.PLAYER},
        )
        assert join.status_code == 201, join.text
        assert join.json()["tenant_id"] == str(tenant_id)
        assert join.json()["role"] == roles.PLAYER

        # /v1/me now shows the tenant + role
        me = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert me.status_code == 200
        body = me.json()
        assert body["email"] == session["email"]
        assert len(body["memberships"]) == 1
        assert body["memberships"][0]["tenant_id"] == str(tenant_id)
        assert body["memberships"][0]["role"] == roles.PLAYER

    async def test_reject_unknown_role(
        self, client: httpx.AsyncClient, tenant_id: uuid.UUID
    ) -> None:
        session = await _register_and_login(client)
        r = await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {session['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": "not-a-role"},
        )
        assert r.status_code == 400

    async def test_reject_platform_admin_grant(
        self, client: httpx.AsyncClient, tenant_id: uuid.UUID
    ) -> None:
        """platform_admin is set through ops paths, not this endpoint."""
        session = await _register_and_login(client)
        r = await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {session['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": roles.PLATFORM_ADMIN},
        )
        assert r.status_code == 403


class TestPortableIdentityENG002:
    """The headline test — AC-M02-03."""

    async def test_leaving_tenant_retains_person_and_history(
        self,
        client: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        session = await _register_and_login(client)

        # Join the tenant.
        join = await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {session['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": roles.PLAYER},
        )
        membership_id = join.json()["id"]

        # Leave it.
        leave = await client.delete(
            f"/v1/memberships/{membership_id}",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert leave.status_code == 204

        # /v1/me still returns the same person, but with zero memberships.
        me = await client.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {session['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["memberships"] == []

        # Log in again from scratch — credentials still work, same person_id.
        relogin = await client.post(
            "/v1/auth/login",
            json={"email": session["email"], "password": session["password"]},
        )
        assert relogin.status_code == 200

        # Membership can no longer be re-fetched or re-deleted.
        second_leave = await client.delete(
            f"/v1/memberships/{membership_id}",
            headers={"Authorization": f"Bearer {relogin.json()['access_token']}"},
        )
        assert second_leave.status_code == 404


class TestRolesInJWT:
    async def test_login_populates_roles_from_memberships(
        self,
        client: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        import jwt as pyjwt

        session = await _register_and_login(client)
        # Before any membership, the login's roles claim is empty.
        access = pyjwt.decode(session["access_token"], options={"verify_signature": False})
        assert access["roles"] == []

        await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {session['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": roles.COACH},
        )

        # Fresh login now carries the coach role in the token.
        login2 = await client.post(
            "/v1/auth/login",
            json={"email": session["email"], "password": session["password"]},
        )
        access2 = pyjwt.decode(login2.json()["access_token"], options={"verify_signature": False})
        assert access2["roles"] == [roles.COACH]


class TestLeaveSecurity:
    async def test_cannot_leave_another_persons_membership(
        self,
        client: httpx.AsyncClient,
        tenant_id: uuid.UUID,
    ) -> None:
        alice = await _register_and_login(client)
        bob = await _register_and_login(client)

        # Alice joins.
        alice_join = await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {alice['access_token']}",
                "Idempotency-Key": f"idem-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tenant_id), "role": roles.PLAYER},
        )
        alice_mid = alice_join.json()["id"]

        # Bob tries to delete alice's membership. Must be 403.
        bob_delete = await client.delete(
            f"/v1/memberships/{alice_mid}",
            headers={"Authorization": f"Bearer {bob['access_token']}"},
        )
        assert bob_delete.status_code == 403
