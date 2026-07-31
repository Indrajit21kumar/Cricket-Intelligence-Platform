"""RBAC negative + positive access tests for the admin console shell (M20 Step 2).

AC-M20-01: M20 is accessible only to platform_admin. This is the ONE
thing every future admin route inherits for free by depending on
:data:`admin_service.routes.require_admin` — this file proves that
dependency actually denies by default.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest

from cip_core import roles

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


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


def _headers(person_id: uuid.UUID, *claim_roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(person_id, *claim_roles)}"}


class TestWhoAmIAccess:
    async def test_unauthenticated_call_is_rejected(
        self, integration_app: httpx.AsyncClient
    ) -> None:
        r = await integration_app.get("/v1/admin/whoami")
        assert r.status_code == 401

    async def test_non_admin_role_is_forbidden(self, integration_app: httpx.AsyncClient) -> None:
        person_id = uuid.uuid4()
        r = await integration_app.get("/v1/admin/whoami", headers=_headers(person_id, roles.COACH))
        assert r.status_code == 403

    async def test_academy_admin_is_not_platform_admin(
        self, integration_app: httpx.AsyncClient
    ) -> None:
        """A tenant-level admin role is NOT the platform-wide role (deny-by-default)."""
        person_id = uuid.uuid4()
        r = await integration_app.get(
            "/v1/admin/whoami", headers=_headers(person_id, roles.ACADEMY_ADMIN)
        )
        assert r.status_code == 403

    async def test_platform_admin_reaches_whoami(self, integration_app: httpx.AsyncClient) -> None:
        person_id = uuid.uuid4()
        r = await integration_app.get(
            "/v1/admin/whoami", headers=_headers(person_id, roles.PLATFORM_ADMIN)
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["person_id"] == str(person_id)
        assert body["roles"] == [roles.PLATFORM_ADMIN]
