"""M17 learning schema: training_plans + plan_evaluations (tenant RLS).

Revision ID: 0001_learning_schema
Revises:
Create Date: 2026-07-31

Creates the learning-service tables per M17 §9. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

Both tables are tenant-scoped with RLS + FORCE + tenant_isolation, exactly
like M10/M11/M13/M14/M15: a training plan is personal data (§11), unlike
M16's processing log (person-anchored, no tenant) or M12's global knowledge.

``training_plans.session_ref`` is the ``dna.updated`` cycle that produced
this plan version (M17 triggers on that event, §8) — ``UNIQUE(tenant_id,
person_id, session_ref)`` is the idempotency anchor (NFR-M17-03). Plans are
append-only history: a new cycle inserts a new row and flips ``active`` on
the previous one, never overwriting it — the same "reconstructable past
state" principle every longitudinal table in this build follows.

Each ``items`` entry links to the finding/fault it addresses (NFR-M17-04,
AC-M17-06): ``{finding_ref, drill_name, objective, dose, target_ref}``.
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

revision: str = "0001_learning_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("training_plans", "plan_evaluations")


def upgrade() -> None:
    op.create_table(
        "training_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The dna.updated cycle that produced this plan version (idempotency).
        sa.Column("session_ref", sa.Text, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),  # cognitive|associative|autonomous
        # [{finding_ref, drill_name, objective, dose, target_ref}, ...]
        sa.Column("items", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column(
            "targets", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        # Only one plan per player is "active" (the current one); older plans
        # are retained as append-only history, never overwritten.
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("schema_version", sa.Text, nullable=False),
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
        sa.CheckConstraint(
            "stage IN ('cognitive', 'associative', 'autonomous')", name="ck_training_plans_stage"
        ),
    )
    op.create_index("ix_training_plans_tenant", "training_plans", ["tenant_id"])
    op.create_index(
        "ix_training_plans_player_history",
        "training_plans",
        ["person_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_training_plans_active",
        "training_plans",
        ["person_id"],
        postgresql_where=sa.text("active"),
    )
    op.create_unique_constraint(
        "uq_training_plans_session",
        "training_plans",
        ["tenant_id", "person_id", "session_ref"],
    )

    op.create_table(
        "plan_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("training_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_ref", sa.Text, nullable=False),
        sa.Column("met", sa.Boolean, nullable=False),
        sa.Column("evidence_ref", sa.Text, nullable=True),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_plan_evaluations_plan", "plan_evaluations", ["plan_id"])

    for table in TENANT_SCOPED_TABLES:
        for stmt in enable_rls_statements(table):
            op.execute(stmt)
        op.execute(tenant_isolation_policy_sql(table))
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(drop_tenant_isolation_policy_sql(table))
        for stmt in disable_rls_statements(table):
            op.execute(stmt)
    op.drop_table("plan_evaluations")
    op.drop_table("training_plans")
