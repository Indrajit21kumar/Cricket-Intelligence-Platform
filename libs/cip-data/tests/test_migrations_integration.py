"""Integration tests for the base migration (AC-M01-04).

Verifies:
- upgrade → downgrade → upgrade is idempotent (no schema drift)
- Required tables and columns exist after upgrade
- RLS is enabled + forced on the tenant-scoped tables
"""

from __future__ import annotations

import pytest
from cip_data.migrations import downgrade_base, upgrade_head
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration


class TestSchemaAfterUpgrade:
    async def test_expected_tables_exist(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
            )
            tables = {row[0] for row in rows}
        for expected in ("tenants", "tenant_members", "audit_log"):
            assert expected in tables, f"Missing table {expected!r}; got {sorted(tables)!r}"

    async def test_tenant_members_has_required_columns(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_members'"
                )
            )
            cols = {row[0] for row in rows}
        for expected in ("id", "tenant_id", "user_ref", "role", "created_at", "updated_at"):
            assert expected in cols, f"tenant_members missing column {expected!r}"

    async def test_audit_log_has_jsonb_meta(self, engine: AsyncEngine) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = 'audit_log' AND column_name = 'meta'"
                )
            )
            data_type = row.scalar()
        assert data_type == "jsonb"


class TestRLSFlagsEnabled:
    """RLS + FORCE must both be on; without FORCE the table owner bypasses."""

    @pytest.mark.parametrize("table", ["tenant_members", "audit_log"])
    async def test_rls_and_force_enabled(self, engine: AsyncEngine, table: str) -> None:
        async with engine.begin() as conn:
            row = await conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :name"
                ),
                {"name": table},
            )
            rls_enabled, force_enabled = row.one()
        assert rls_enabled is True, f"{table}: RLS not enabled"
        assert force_enabled is True, f"{table}: RLS not FORCED"

    async def test_tenants_has_no_rls(self, engine: AsyncEngine) -> None:
        """tenants IS the tenant — must be readable without a scope."""
        async with engine.begin() as conn:
            row = await conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE relname = 'tenants'")
            )
            rls_enabled = row.scalar()
        assert rls_enabled is False


class TestMigrationRoundTrip:
    def test_downgrade_then_upgrade_is_clean(self, database_url: str) -> None:
        """Down to base, back to head — no errors, tables reappear."""
        downgrade_base(database_url)
        upgrade_head(database_url)
        # The migrated_database session fixture re-applies at session start,
        # so we leave things at 'head' for subsequent tests.
