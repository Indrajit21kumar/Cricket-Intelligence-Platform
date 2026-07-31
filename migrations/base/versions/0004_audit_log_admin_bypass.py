"""Read-only platform_admin bypass on audit_log's RLS — M20 Step 7, FR-M20-07.

Revision ID: 0004_audit_log_admin_bypass
Revises: 0003_tenants_status
Create Date: 2026-07-31

Every other service's RLS keeps a tenant-scoped row invisible outside that
tenant's own session — exactly right everywhere else, wrong for the one
place a platform_admin's job requires it: searching the platform-wide audit
trail across every tenant (FR-M20-07).

This adds a narrow OR clause to the existing ``tenant_isolation`` policy:
a session that sets ``cip.platform_admin_bypass`` may SELECT any row. The
``WITH CHECK`` clause deliberately does NOT gain the same bypass — a
session under this flag can still only INSERT/UPDATE within its own tenant
scope (or NULL/platform rows), the same as before. This is READ-only
widening, and only for a GUC no code other than admin-service's audit
search route ever sets.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004_audit_log_admin_bypass"
down_revision: str | Sequence[str] | None = "0003_tenants_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUC = "cip.tenant_id"
ADMIN_BYPASS_GUC = "cip.platform_admin_bypass"


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON audit_log
            USING (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid
                OR NULLIF(current_setting('{ADMIN_BYPASS_GUC}', true), '') = 'true'
            )
            WITH CHECK (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON audit_log
            USING (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid
            )
            WITH CHECK (
                tenant_id IS NULL
                OR tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid
            )
        """
    )
