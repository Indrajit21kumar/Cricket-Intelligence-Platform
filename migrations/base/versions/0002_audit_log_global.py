"""Allow platform-level (non-tenant) audit rows in audit_log.

Revision ID: 0002_audit_log_global
Revises: 0001_base_schema
Create Date: 2026-07-21

M01 created ``audit_log`` as a strictly tenant-scoped table. But identity
actions (M02) — registration, consent, account deletion — are GLOBAL: they
happen against a person, not within a tenant. FR-M02-09 still requires them
recorded in ``audit_log``.

This migration:
- makes ``tenant_id`` nullable, and
- replaces the tenant_isolation policy with one that ALSO admits NULL-tenant
  (platform) rows. Tenant-scoped rows remain isolated to their tenant; the
  platform rows are visible platform-wide (they belong to no single tenant).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002_audit_log_global"
down_revision: str | Sequence[str] | None = "0001_base_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GUC = "cip.tenant_id"


def upgrade() -> None:
    op.execute("ALTER TABLE audit_log ALTER COLUMN tenant_id DROP NOT NULL")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    # NULL tenant_id = platform action (visible everywhere); a set tenant_id
    # is isolated to that tenant.
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


def downgrade() -> None:
    # Restore the strict tenant-only policy + NOT NULL. Any NULL-tenant rows
    # must be cleared first or the NOT NULL restore fails.
    op.execute("DELETE FROM audit_log WHERE tenant_id IS NULL")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON audit_log")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON audit_log
            USING (tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('{GUC}', true), '')::uuid)
        """
    )
    op.execute("ALTER TABLE audit_log ALTER COLUMN tenant_id SET NOT NULL")
