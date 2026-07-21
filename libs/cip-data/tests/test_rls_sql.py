"""Unit tests for :mod:`cip_data.rls` — SQL generator functions."""

from __future__ import annotations

from cip_data.rls import (
    TENANT_GUC,
    disable_rls_statements,
    drop_tenant_isolation_policy_sql,
    enable_rls_statements,
    tenant_isolation_policy_sql,
)


class TestEnableRLS:
    def test_returns_enable_and_force(self) -> None:
        stmts = enable_rls_statements("widgets")
        assert len(stmts) == 2
        # FORCE is critical — without it the table owner bypasses RLS
        # and negative tests would silently pass. See rls.py docstring.
        assert any("ENABLE ROW LEVEL SECURITY" in s for s in stmts)
        assert any("FORCE ROW LEVEL SECURITY" in s for s in stmts)

    def test_no_trailing_semicolons(self) -> None:
        # asyncpg's prepared-statement protocol rejects multiple statements
        # per call, so each statement must be its own list entry with no
        # embedded ';'.
        for stmt in enable_rls_statements("widgets"):
            assert ";" not in stmt


class TestTenantIsolationPolicy:
    def test_uses_cip_tenant_guc(self) -> None:
        sql = tenant_isolation_policy_sql("widgets")
        assert TENANT_GUC in sql
        assert "current_setting" in sql
        assert "::uuid" in sql

    def test_includes_using_and_with_check(self) -> None:
        # USING blocks reads/updates of other tenants; WITH CHECK blocks
        # inserts/updates that place a row under a different tenant.
        sql = tenant_isolation_policy_sql("widgets")
        assert "USING" in sql
        assert "WITH CHECK" in sql

    def test_custom_policy_name(self) -> None:
        sql = tenant_isolation_policy_sql("widgets", policy_name="my_policy")
        assert "CREATE POLICY my_policy ON widgets" in sql


class TestDrop:
    def test_drop_policy(self) -> None:
        sql = drop_tenant_isolation_policy_sql("widgets")
        assert "DROP POLICY IF EXISTS tenant_isolation ON widgets" in sql

    def test_disable_rls(self) -> None:
        stmts = disable_rls_statements("widgets")
        assert any("NO FORCE ROW LEVEL SECURITY" in s for s in stmts)
        assert any("DISABLE ROW LEVEL SECURITY" in s for s in stmts)
