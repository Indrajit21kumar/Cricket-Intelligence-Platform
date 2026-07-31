"""Add ``status`` to ``tenants`` — M20 Step 3 support/moderation action.

Revision ID: 0003_tenants_status
Revises: 0002_audit_log_global
Create Date: 2026-07-31

M20's admin console needs to suspend/restore a tenant (FR-M20-01, the
``POST /v1/admin/tenants/{id}/action`` route), and the base ``tenants``
table (M01) had no status of its own — every tenant was implicitly active.
Additive, defaulted column: no existing row or query changes behaviour.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_tenants_status"
down_revision: str | Sequence[str] | None = "0002_audit_log_global"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'active'")),
    )
    op.create_check_constraint(
        "ck_tenants_status", "tenants", "status IN ('active', 'suspended')"
    )
    op.create_index("ix_tenants_status", "tenants", ["status"])


def downgrade() -> None:
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_constraint("ck_tenants_status", "tenants", type_="check")
    op.drop_column("tenants", "status")
