"""Integration tests for the M03 billing schema (Step 1)."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import downgrade_base, upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"

DEFAULT_URL = "postgresql+asyncpg://cip:cip@localhost:5432/cip"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", DEFAULT_URL)


@pytest.fixture(scope="module")
def migrated_billing_schema() -> str:
    """Ensure base + billing migrations are applied (idempotent).

    Does NOT downgrade base — other services (e.g. identity) hold FKs to the
    base tables. Billing-only rollback is exercised in
    :class:`TestBillingMigrationRollback`.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BILLING_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def engine(migrated_billing_schema: str) -> AsyncIterator[AsyncEngine]:
    eng = build_engine(migrated_billing_schema)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return build_session_factory(engine)


class TestBillingMigrationRollback:
    """Billing migration rolls back + re-applies cleanly (Step 1 Done-when).

    Billing-only: drops billing tables, re-applies them. Never touches base,
    so it doesn't disturb other services sharing the DB.
    """

    def test_downgrade_then_upgrade_is_clean(self, migrated_billing_schema: str) -> None:
        downgrade_base(migrated_billing_schema, migrations_dir=BILLING_MIGRATIONS)
        upgrade_head(migrated_billing_schema, migrations_dir=BILLING_MIGRATIONS)


class TestTables:
    async def test_all_billing_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = {r[0] for r in rows}
        for expected in (
            "plans",
            "plan_entitlements",
            "subscriptions",
            "usage_records",
            "invoices",
            "seats",
            "billing_audit",
        ):
            assert expected in tables, f"missing {expected}; got {sorted(tables)}"


class TestRLSFlags:
    @pytest.mark.parametrize(
        "table", ["subscriptions", "usage_records", "invoices", "seats", "billing_audit"]
    )
    async def test_tenant_scoped_tables_have_rls(self, engine: AsyncEngine, table: str) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :name"
                ),
                {"name": table},
            )
            rls, force = row.one()
        assert rls is True and force is True

    async def test_plans_catalogue_has_no_rls(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'plans'")
            )
            assert row.scalar() is False


async def _make_tenant(session_factory: async_sessionmaker, prefix: str) -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(session_factory) as s:
        await s.execute(
            text("INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}"},
        )
    return tid


async def _seed_plan(session_factory: async_sessionmaker) -> uuid.UUID:
    pid = uuid.uuid4()
    async with admin_session(session_factory) as s:
        await s.execute(
            text("INSERT INTO plans (id, code, name, version) VALUES (:id, :c, :n, 1)"),
            {"id": pid, "c": f"plan-{uuid.uuid4().hex[:6]}", "n": "Test Plan"},
        )
    return pid


class TestSubscriptionsRLS:
    async def test_cross_tenant_subscription_blocked(
        self, session_factory: async_sessionmaker
    ) -> None:
        tenant_a = await _make_tenant(session_factory, "acad-a")
        tenant_b = await _make_tenant(session_factory, "acad-b")
        plan_id = await _seed_plan(session_factory)

        async def _add_sub(tid: uuid.UUID) -> None:
            async with tenant_session(session_factory, tenant_id=tid) as s:
                await s.execute(
                    text(
                        "INSERT INTO subscriptions "
                        "  (id, tenant_id, subject_ref, plan_id, status, "
                        "   period_start, period_end) "
                        "VALUES (:id, :tid, :subj, :plan, 'active', now(), "
                        "        now() + interval '30 days')"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": tid,
                        "subj": f"tenant:{tid}",
                        "plan": plan_id,
                    },
                )

        await _add_sub(tenant_a)
        await _add_sub(tenant_b)

        # Tenant A sees only its own subscription.
        async with tenant_session(session_factory, tenant_id=tenant_a) as s:
            rows = await s.execute(text("SELECT tenant_id FROM subscriptions"))
            visible = {r[0] for r in rows}
        assert visible == {tenant_a}
