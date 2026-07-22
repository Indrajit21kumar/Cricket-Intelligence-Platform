"""Subscription lifecycle + proration (M03 Step 5, AC-M03-01, FR-M03-02/06).

Covers:
- POST /v1/subscriptions — subscribe (starter, then upgrade to pro)
- PATCH /v1/subscriptions/{id} — upgrade prorated / cancel
- GET  /v1/subscriptions/{id} — status + entitlements after change
- RBAC: unauthenticated (401) + wrong-role (403) rejected
- Cache: entitlement fresh cache invalidated on plan change

Uses hand-signed JWTs (same pattern as identity-service RBAC tests).
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
from sqlalchemy import text

from billing_service.domain.catalogue import seed_catalogue
from billing_service.main import create_app
from cip_core import roles
from cip_core.settings import get_settings
from cip_data.engine import (
    admin_session,
    build_engine,
    build_session_factory,
)
from cip_data.migrations import upgrade_head

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic signing key for hand-crafted access tokens."""
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BILLING_MIGRATIONS)
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_tenant(migrated_db: str) -> uuid.UUID:
    """Seed the plan catalogue + a fresh tenant. Returns tenant_id."""
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await seed_catalogue(s)
            await s.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"
                ),
                {"id": tid, "n": f"acad-{uuid.uuid4().hex[:8]}"},
            )
    finally:
        await engine.dispose()
    return tid


class TestSubscribe:
    async def test_subscribe_returns_active_subscription(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        token = _access_token(roles.ACADEMY_ADMIN)

        r = await client.post(
            "/v1/subscriptions",
            headers=_auth(token),
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "active"
        assert body["plan_code"] == "starter"
        assert body["subject_ref"] == f"tenant:{tid}"

    async def test_subscribe_trialing_starts_on_trial(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        r = await client.post(
            "/v1/subscriptions",
            headers=_auth(_access_token(roles.ACADEMY_ADMIN)),
            json={"subject": f"tenant:{tid}", "plan_code": "pro", "trialing": True},
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "trialing"

    async def test_subscribe_conflict_when_already_active(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        first = await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )
        assert first.status_code == 201
        second = await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "pro"},
        )
        assert second.status_code == 409

    async def test_subscribe_unknown_plan_404(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        r = await client.post(
            "/v1/subscriptions",
            headers=_auth(_access_token(roles.ACADEMY_ADMIN)),
            json={"subject": f"tenant:{tid}", "plan_code": "ghost"},
        )
        assert r.status_code == 404


class TestRBAC:
    async def test_unauthenticated_rejected_401(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        r = await client.post(
            "/v1/subscriptions",
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )
        assert r.status_code == 401

    async def test_wrong_role_forbidden_403(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        r = await client.post(
            "/v1/subscriptions",
            headers=_auth(_access_token(roles.PLAYER)),  # not a tenant admin
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )
        assert r.status_code == 403


class TestChange:
    async def test_upgrade_prorated_net_positive_and_plan_updated(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "starter"},
            )
        ).json()

        r = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "pro"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Plan moved forward.
        assert body["subscription"]["plan_code"] == "pro"
        assert body["subscription"]["status"] == "active"
        # Prorated: Starter (0) -> Pro (49900) -> credit=0, charge>0, net>0.
        p = body["proration"]
        assert p is not None
        assert p["credit_minor"] == 0
        assert p["charge_minor"] > 0
        assert p["net_minor"] == p["charge_minor"]
        assert 0.0 < p["fraction_remaining"] <= 1.0

    async def test_downgrade_prorated_net_negative(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "pro"},
            )
        ).json()

        r = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )
        assert r.status_code == 200, r.text
        p = r.json()["proration"]
        # Credit for unused Pro, no forward charge.
        assert p["credit_minor"] > 0
        assert p["charge_minor"] == 0
        assert p["net_minor"] < 0

    async def test_cancel_terminates_subscription(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "pro"},
            )
        ).json()

        r = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "action": "cancel"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["subscription"]["status"] == "canceled"
        assert body["proration"] is None

        # Cancelled -> entitlement check no longer allowed (no active sub).
        chk = await client.post(
            "/v1/entitlements/check",
            json={"subject": f"tenant:{tid}", "key": "feature.ai_coach"},
        )
        assert chk.status_code == 200
        assert chk.json()["allowed"] is False

    async def test_patch_both_fields_rejected_400(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "starter"},
            )
        ).json()

        r = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "pro", "action": "cancel"},
        )
        assert r.status_code == 400

    async def test_patch_same_plan_rejected_400(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "pro"},
            )
        ).json()

        r = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "pro"},
        )
        assert r.status_code == 400


class TestEntitlementCacheInvalidation:
    async def test_plan_change_invalidates_cache_immediately(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """AC-M03-01 tail: entitlements update correctly after a change.

        Before Step 5 the entitlement check cached the resolved plan for 5
        min; without invalidation, an upgrade wouldn't be visible until the
        FRESH TTL expired. This proves the route drops the fresh key so the
        next check re-resolves.
        """
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "starter"},
            )
        ).json()

        # Prime the entitlement cache while on Starter — ai_coach is off.
        before = await client.post(
            "/v1/entitlements/check",
            json={"subject": f"tenant:{tid}", "key": "feature.ai_coach"},
        )
        assert before.status_code == 200
        assert before.json()["allowed"] is False

        # Upgrade to Pro (which enables feature.ai_coach).
        up = await client.patch(
            f"/v1/subscriptions/{sub['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "pro"},
        )
        assert up.status_code == 200, up.text

        # Same key, immediately after: must reflect the new plan.
        after = await client.post(
            "/v1/entitlements/check",
            json={"subject": f"tenant:{tid}", "key": "feature.ai_coach"},
        )
        assert after.status_code == 200
        assert after.json()["allowed"] is True


class TestGet:
    async def test_get_returns_current_state(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        created = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "starter"},
            )
        ).json()

        r = await client.get(
            f"/v1/subscriptions/{created['id']}?subject=tenant:{tid}", headers=headers
        )
        assert r.status_code == 200, r.text
        assert r.json()["id"] == created["id"]
        assert r.json()["plan_code"] == "starter"

    async def test_get_unknown_404(self, client: httpx.AsyncClient, migrated_db: str) -> None:
        # Need a real tenant so RLS doesn't reject the SELECT for a
        # missing GUC before we even get to the not-found check.
        tid = await _seed_tenant(migrated_db)
        r = await client.get(
            f"/v1/subscriptions/{uuid.uuid4()}?subject=tenant:{tid}",
            headers=_auth(_access_token(roles.ACADEMY_ADMIN)),
        )
        assert r.status_code == 404

    async def test_get_wrong_subject_returns_404(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """Cross-tenant fetch attempt gets an honest 404, not the row.

        RLS enforces this in the DB — the router doesn't need to double-check.
        """
        tid_a = await _seed_tenant(migrated_db)
        tid_b = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        created = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid_a}", "plan_code": "starter"},
            )
        ).json()

        # Ask for A's subscription id under B's subject -> RLS hides it.
        r = await client.get(
            f"/v1/subscriptions/{created['id']}?subject=tenant:{tid_b}", headers=headers
        )
        assert r.status_code == 404
