"""RBAC role x endpoint matrix (M02 Step 4 / AC-M02-02).

Uses hand-crafted JWTs with each role and hits the admin-ping endpoint.
Roles from real memberships get populated at Step 5; until then, hand-signed
tokens are the cleanest way to prove the deny-by-default enforcement.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import pytest_asyncio

from cip_core import roles
from cip_data.migrations import upgrade_head
from identity_service.main import create_app

# Must match the constant the conftest.py autouse fixture pins into env.
TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

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


def _access_token(*claim_roles: str) -> str:
    """Build an access-type JWT with the given roles."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


class TestAdminPingDenyByDefault:
    """AC-M02-02: every protected endpoint denies by default."""

    async def test_no_auth_header_401(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/v1/auth/admin/ping")
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"


class TestAllowedRoles:
    @pytest.mark.parametrize("role", roles.TENANT_ADMIN_ROLES)
    async def test_tenant_admin_roles_allowed(self, client: httpx.AsyncClient, role: str) -> None:
        response = await client.get(
            "/v1/auth/admin/ping",
            headers={"Authorization": f"Bearer {_access_token(role)}"},
        )
        assert response.status_code == 200, response.text
        assert role in response.json()["roles"]


class TestDeniedRoles:
    @pytest.mark.parametrize("role", [roles.PLAYER, roles.PARENT, roles.COACH])
    async def test_non_admin_roles_denied(self, client: httpx.AsyncClient, role: str) -> None:
        response = await client.get(
            "/v1/auth/admin/ping",
            headers={"Authorization": f"Bearer {_access_token(role)}"},
        )
        assert response.status_code == 403
        body = response.json()
        assert body["error"]["code"] == "FORBIDDEN"
        assert body["error"]["details"]["required_any_of"] == list(roles.TENANT_ADMIN_ROLES)

    async def test_no_roles_denied(self, client: httpx.AsyncClient) -> None:
        response = await client.get(
            "/v1/auth/admin/ping",
            headers={"Authorization": f"Bearer {_access_token()}"},
        )
        assert response.status_code == 403


class TestMultiRolePrincipal:
    """A person can have multiple roles (member of multiple tenants)."""

    async def test_any_matching_role_grants_access(self, client: httpx.AsyncClient) -> None:
        # Principal is a player in academy A + org_admin in org B.
        response = await client.get(
            "/v1/auth/admin/ping",
            headers={"Authorization": f"Bearer {_access_token(roles.PLAYER, roles.ORG_ADMIN)}"},
        )
        assert response.status_code == 200
