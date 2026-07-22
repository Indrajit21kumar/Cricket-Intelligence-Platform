"""M03 billing schema: plans, entitlements, subscriptions, usage, invoices, seats, audit.

Revision ID: 0001_billing_schema
Revises:
Create Date: 2026-07-22

Creates the billing-service tables per M03 §9. Depends on the M01 base
migration (``tenants`` must exist for the tenant FKs).

Table ownership:
- plans, plan_entitlements   global catalogue (no RLS — readable platform-wide)
- subscriptions              tenant-scoped — RLS
- usage_records              tenant-scoped — RLS; UNIQUE idempotency_key (NFR-M03-02)
- invoices                   tenant-scoped — RLS
- seats                      tenant-scoped — RLS
- billing_audit              tenant-scoped — RLS; immutable billing log
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from cip_data.rls import (
    disable_rls_statements,
    drop_tenant_isolation_policy_sql,
    enable_rls_statements,
    tenant_isolation_policy_sql,
)

revision: str = "0001_billing_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TENANT_SCOPED_TABLES = (
    "subscriptions",
    "usage_records",
    "invoices",
    "seats",
    "billing_audit",
)
GLOBAL_TABLES = ("plans", "plan_entitlements")


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    # --- catalogue (global) ------------------------------------------------
    op.create_table(
        "plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.Text, nullable=False),  # 'starter' | 'pro' | ...
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column(
            "price_minor",
            sa.BigInteger,
            nullable=False,
            server_default=sa.text("0"),
        ),  # price in minor units (paise/cents)
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'INR'")),
        *_timestamps(),
    )
    op.create_unique_constraint("uq_plans_code_version", "plans", ["code", "version"])

    op.create_table(
        "plan_entitlements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.Text, nullable=False),  # e.g. 'analysis.quota_monthly'
        sa.Column("value", sa.Text, nullable=False),  # stringified int/bool
        *_timestamps(),
    )
    op.create_index("ix_plan_entitlements_plan_id", "plan_entitlements", ["plan_id"])
    op.create_unique_constraint(
        "uq_plan_entitlements_plan_key", "plan_entitlements", ["plan_id", "key"]
    )

    # --- subscriptions (tenant-scoped) ------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("subject_ref", sa.Text, nullable=False),  # 'person:<uuid>' | 'tenant:<uuid>'
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'active'"),
        ),  # trialing | active | past_due | suspended | canceled
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_ref", sa.Text, nullable=True),  # provider subscription id
        *_timestamps(),
    )
    op.create_index("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    op.create_index("ix_subscriptions_subject", "subscriptions", ["subject_ref"])

    # --- usage_records (tenant-scoped) ------------------------------------
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("meter_key", sa.Text, nullable=False),  # 'analysis.consumed'
        sa.Column("qty", sa.BigInteger, nullable=False, server_default=sa.text("1")),
        sa.Column("period", sa.Text, nullable=False),  # 'YYYY-MM' billing period bucket
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_usage_subscription", "usage_records", ["subscription_id"])
    # Exactly-once per unit within a period (NFR-M03-02).
    op.create_unique_constraint("uq_usage_idempotency", "usage_records", ["idempotency_key"])

    # --- invoices (tenant-scoped) -----------------------------------------
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.Text, nullable=False, server_default=sa.text("'INR'")),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'open'"),
        ),  # open | paid | failed | void
        sa.Column("provider_ref", sa.Text, nullable=True),  # provider invoice/charge id
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_invoices_subscription", "invoices", ["subscription_id"])
    op.create_unique_constraint("uq_invoices_provider_ref", "invoices", ["provider_ref"])

    # --- seats (tenant-scoped) --------------------------------------------
    op.create_table(
        "seats",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("member_ref", sa.Text, nullable=False),  # 'person:<uuid>'
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_seats_subscription", "seats", ["subscription_id"])
    op.create_unique_constraint(
        "uq_seats_subscription_member", "seats", ["subscription_id", "member_ref"]
    )

    # --- billing_audit (tenant-scoped) ------------------------------------
    op.create_table(
        "billing_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
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
    op.create_index("ix_billing_audit_tenant", "billing_audit", ["tenant_id"])

    # --- RLS on tenant-scoped tables --------------------------------------
    for table in TENANT_SCOPED_TABLES:
        for stmt in enable_rls_statements(table):
            op.execute(stmt)
        op.execute(tenant_isolation_policy_sql(table))

    # --- grants to the app role -------------------------------------------
    for table in (*GLOBAL_TABLES, *TENANT_SCOPED_TABLES):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(drop_tenant_isolation_policy_sql(table))
        for stmt in disable_rls_statements(table):
            op.execute(stmt)

    op.drop_table("billing_audit")
    op.drop_table("seats")
    op.drop_table("invoices")
    op.drop_table("usage_records")
    op.drop_table("subscriptions")
    op.drop_table("plan_entitlements")
    op.drop_table("plans")
