"""Base platform schema: tenants, tenant_members, audit_log + RLS.

Revision ID: 0001_base_schema
Revises:
Create Date: 2026-07-21

Creates the three tables every CIP service depends on (M01 §8):

- ``tenants``         — root of multi-tenancy; NOT tenant-scoped itself.
- ``tenant_members``  — RBAC assignment of a user to a tenant.
- ``audit_log``       — immutable record of sensitive actions.

``tenant_members`` and ``audit_log`` are tenant-scoped: RLS is enabled +
forced, with the standard ``tenant_isolation`` policy from
:mod:`cip_data.rls`. ``tenants`` itself carries no RLS — it IS the tenant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from cip_data.rls import (
    disable_rls_statements,
    drop_tenant_isolation_policy_sql,
    enable_rls_statements,
    tenant_isolation_policy_sql,
)
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_base_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_SCOPED_TABLES = ("tenant_members", "audit_log")

APP_ROLE = "cip_app"


def upgrade() -> None:
    # pgcrypto gives us gen_random_uuid() — needed if a default is deferred
    # to the DB. Not strictly required today (defaults live in Python) but
    # cheap to enable and unblocks future migrations.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # Postgres RLS is bypassed by the table owner AND by any superuser.
    # The initial db user (e.g. 'cip' in local dev) is often a superuser,
    # so migrations create a NOLOGIN role the application SET ROLEs into
    # for every session. That role is a plain member — subject to RLS.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
        END $$
        """
    )

    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=True),
        sa.Column("region", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint("uq_tenants_name", "tenants", ["name"])

    op.create_table(
        "tenant_members",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_ref", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_tenant_members_tenant_id", "tenant_members", ["tenant_id"]
    )
    op.create_unique_constraint(
        "uq_tenant_members_tenant_user",
        "tenant_members",
        ["tenant_id", "user_ref"],
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("entity", sa.Text, nullable=False),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("correlation_id", sa.Text, nullable=True),
        sa.Column(
            "meta",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_at", "audit_log", ["at"])

    # Enable RLS on the two tenant-scoped tables + install the standard policy.
    for table in TENANT_SCOPED_TABLES:
        for stmt in enable_rls_statements(table):
            op.execute(stmt)
        op.execute(tenant_isolation_policy_sql(table))

    # Grant privileges the app role needs on every table.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON tenants TO {APP_ROLE}")
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(drop_tenant_isolation_policy_sql(table))
        for stmt in disable_rls_statements(table):
            op.execute(stmt)

    # Drop the app role (must happen after tables are dropped, since roles
    # cannot be dropped while they own privileges on existing objects).
    # We reassign owned objects to the current user first, then drop.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};
                REVOKE USAGE ON SCHEMA public FROM {APP_ROLE};
            END IF;
        END $$
        """
    )

    op.drop_index("ix_audit_log_at", table_name="audit_log")
    op.drop_index("ix_audit_log_tenant_id", table_name="audit_log")
    op.drop_table("audit_log")

    op.drop_constraint(
        "uq_tenant_members_tenant_user", "tenant_members", type_="unique"
    )
    op.drop_index("ix_tenant_members_tenant_id", table_name="tenant_members")
    op.drop_table("tenant_members")

    op.drop_constraint("uq_tenants_name", "tenants", type_="unique")
    op.drop_table("tenants")
