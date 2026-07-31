"""Integration tests for the admin-action audit helper (M20 Step 2, FR-M20-09).

Every privileged action must land in BOTH the service-local ``admin_actions``
table and the platform-wide ``audit_log`` — this proves both writes actually
happen from a single call.
"""

from __future__ import annotations

import uuid

import pytest
from admin_service.domain.audit import record_admin_action
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


async def _make_tenant(sf: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


class TestRecordAdminAction:
    async def test_writes_to_admin_actions(self, session_factory: async_sessionmaker) -> None:
        admin_ref = str(uuid.uuid4())
        tenant_ref = await _make_tenant(session_factory, "adm-actions")
        async with admin_session(session_factory) as s:
            action_id = await record_admin_action(
                s,
                admin_ref=admin_ref,
                action="tenant.suspended",
                target=f"tenant:{tenant_ref}",
                tenant_ref=tenant_ref,
                cross_tenant=True,
                meta={"reason": "non-payment"},
            )
        async with admin_session(session_factory) as s:
            row = (
                (
                    await s.execute(
                        text(
                            "SELECT admin_ref, action, target, tenant_ref, cross_tenant, meta "
                            "FROM admin_actions WHERE id = :id"
                        ),
                        {"id": action_id},
                    )
                )
                .mappings()
                .one()
            )
        assert row["admin_ref"] == admin_ref
        assert row["action"] == "tenant.suspended"
        assert row["target"] == f"tenant:{tenant_ref}"
        assert row["tenant_ref"] == tenant_ref
        assert row["cross_tenant"] is True
        assert row["meta"] == {"reason": "non-payment"}

    async def test_also_writes_to_shared_audit_log(
        self, session_factory: async_sessionmaker
    ) -> None:
        admin_ref = str(uuid.uuid4())
        target = f"tenant:{uuid.uuid4()}"
        async with admin_session(session_factory) as s:
            await record_admin_action(
                s, admin_ref=admin_ref, action="tenant.suspended", target=target
            )
        async with admin_session(session_factory) as s:
            row = (
                (
                    await s.execute(
                        text(
                            "SELECT actor, action, entity FROM audit_log "
                            "WHERE entity = :target AND actor = :admin"
                        ),
                        {"target": target, "admin": admin_ref},
                    )
                )
                .mappings()
                .one()
            )
        assert row["action"] == "admin.tenant.suspended"
        assert row["entity"] == target

    async def test_platform_wide_action_has_null_tenant(
        self, session_factory: async_sessionmaker
    ) -> None:
        """No tenant_ref -- e.g. a platform-wide moderation action -- stays NULL."""
        admin_ref = str(uuid.uuid4())
        target = f"clip:{uuid.uuid4()}"
        async with admin_session(session_factory) as s:
            action_id = await record_admin_action(
                s, admin_ref=admin_ref, action="content.removed", target=target
            )
        async with admin_session(session_factory) as s:
            tenant_ref = (
                await s.execute(
                    text("SELECT tenant_ref FROM admin_actions WHERE id = :id"), {"id": action_id}
                )
            ).scalar_one()
        assert tenant_ref is None
