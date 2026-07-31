"""Route-level integration tests for user/tenant admin + moderation (M20 Step 3).

Exercises the real HTTP surface end to end (not just the domain functions
tested elsewhere) and proves every write lands an ``admin_actions`` row —
the "Done when: Admin/support/moderation actions work + audited" bar Step 3
sets for itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import roles
from cip_data.engine import admin_session, tenant_session

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


def _admin_headers(admin_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(admin_id, roles.PLATFORM_ADMIN)}"}


async def _make_person(sf: async_sessionmaker, *, email: str) -> uuid.UUID:
    pid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO persons (id, email, status) VALUES (:id, :email, 'active')"),
            {"id": pid, "email": email},
        )
    return pid


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


async def _admin_actions_for(sf: async_sessionmaker, target: str) -> list[dict]:
    async with admin_session(sf) as s:
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT action, admin_ref, cross_tenant "
                        "FROM admin_actions WHERE target = :t"
                    ),
                    {"t": target},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


class TestUserAdministration:
    async def test_search_finds_the_seeded_person(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        unique = uuid.uuid4().hex[:8]
        await _make_person(session_factory, email=f"{unique}@example.test")
        admin_id = uuid.uuid4()
        r = await integration_app.get(
            "/v1/admin/users", params={"q": unique}, headers=_admin_headers(admin_id)
        )
        assert r.status_code == 200, r.text
        assert len(r.json()) == 1

    async def test_suspend_then_restore_is_audited(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        pid = await _make_person(session_factory, email=f"{uuid.uuid4().hex}@example.test")
        admin_id = uuid.uuid4()

        r = await integration_app.post(
            f"/v1/admin/users/{pid}/action",
            json={"action": "suspend", "reason": "policy violation"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "suspended"

        r = await integration_app.post(
            f"/v1/admin/users/{pid}/action",
            json={"action": "restore"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "active"

        actions = await _admin_actions_for(session_factory, f"person:{pid}")
        recorded = {a["action"] for a in actions}
        assert recorded == {"user.suspended", "user.restored"}
        assert all(a["admin_ref"] == str(admin_id) for a in actions)
        assert all(a["cross_tenant"] is True for a in actions)

    async def test_action_on_unknown_user_is_404(self, integration_app: httpx.AsyncClient) -> None:
        r = await integration_app.post(
            f"/v1/admin/users/{uuid.uuid4()}/action",
            json={"action": "suspend"},
            headers=_admin_headers(uuid.uuid4()),
        )
        assert r.status_code == 404


class TestTenantAdministration:
    async def test_suspend_then_restore_is_audited(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        tid = await _make_tenant(session_factory, "route-suspend")
        admin_id = uuid.uuid4()

        r = await integration_app.post(
            f"/v1/admin/tenants/{tid}/action",
            json={"action": "suspend", "reason": "non-payment"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "suspended"

        r = await integration_app.get(f"/v1/admin/tenants/{tid}", headers=_admin_headers(admin_id))
        assert r.json()["status"] == "suspended"

        r = await integration_app.post(
            f"/v1/admin/tenants/{tid}/action",
            json={"action": "restore"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "active"

        actions = await _admin_actions_for(session_factory, f"tenant:{tid}")
        assert {a["action"] for a in actions} == {"tenant.suspended", "tenant.restored"}

        # audit_log is RLS-protected: a real (non-NULL) tenant_id row is only
        # visible through a session scoped to that same tenant -- admin_session
        # (no ambient tenant) would see nothing, same as any other RLS table.
        async with tenant_session(session_factory, tenant_id=tid) as s:
            audit_rows = (
                (
                    await s.execute(
                        text("SELECT action FROM audit_log WHERE entity = :e"),
                        {"e": f"tenant:{tid}"},
                    )
                )
                .mappings()
                .all()
            )
        assert {r["action"] for r in audit_rows} == {
            "admin.tenant.suspended",
            "admin.tenant.restored",
        }

    async def test_action_on_unknown_tenant_is_404(
        self, integration_app: httpx.AsyncClient
    ) -> None:
        r = await integration_app.post(
            f"/v1/admin/tenants/{uuid.uuid4()}/action",
            json={"action": "suspend"},
            headers=_admin_headers(uuid.uuid4()),
        )
        assert r.status_code == 404


class TestModeration:
    async def test_flag_then_resolve_flow_is_audited(
        self, integration_app: httpx.AsyncClient, session_factory: async_sessionmaker
    ) -> None:
        admin_id = uuid.uuid4()
        subject = f"video:{uuid.uuid4()}"

        r = await integration_app.post(
            "/v1/admin/moderation",
            json={"subject_ref": subject, "reason": "user reported"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 201, r.text
        case = r.json()
        assert case["status"] == "open"

        r = await integration_app.get(
            "/v1/admin/moderation", params={"status": "open"}, headers=_admin_headers(admin_id)
        )
        assert any(c["id"] == case["id"] for c in r.json())

        r = await integration_app.post(
            f"/v1/admin/moderation/{case['id']}/resolve",
            json={"decision": "actioned", "action_taken": "clip_removed"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "actioned"

        actions = await _admin_actions_for(session_factory, f"case:{case['id']}")
        assert {a["action"] for a in actions} == {"moderation.flagged", "moderation.actioned"}

    async def test_resolving_twice_is_404(self, integration_app: httpx.AsyncClient) -> None:
        admin_id = uuid.uuid4()
        r = await integration_app.post(
            "/v1/admin/moderation",
            json={"subject_ref": f"video:{uuid.uuid4()}", "reason": "dup test"},
            headers=_admin_headers(admin_id),
        )
        case_id = r.json()["id"]
        r = await integration_app.post(
            f"/v1/admin/moderation/{case_id}/resolve",
            json={"decision": "dismissed"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 200
        r = await integration_app.post(
            f"/v1/admin/moderation/{case_id}/resolve",
            json={"decision": "actioned"},
            headers=_admin_headers(admin_id),
        )
        assert r.status_code == 404
