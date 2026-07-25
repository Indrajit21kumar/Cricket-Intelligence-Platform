"""M10 biomechanics schema: biomechanics_reports (one report per stroke).

Revision ID: 0001_biomechanics_schema
Revises:
Create Date: 2026-07-25

Creates the biomechanics-service table per M10 §12. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

M10's output is a compact per-stroke report — the 17 BM metrics plus a quality
block — so it lives entirely in the DB, no object-storage artefact. Tenant-
scoped RLS, correlation-keyed idempotency (one report per stroke).

Three indexes carry §12's operational needs:

- ``(person_id, computed_at DESC)`` — a player's report history, newest first.
- a PARTIAL index over the review queue: rows flagged
  ``out_of_expected_range`` that a human has not yet reviewed. Partial so the
  index stays tiny (almost every report is in-range and reviewed), which is
  exactly what a work queue wants — it indexes only the outstanding work.
- a GIN index on the ``metrics`` JSONB, so M15/M12 can query by metric value
  (e.g. "strokes where BM-04 X-Factor > 40") without a full scan.

``out_of_expected_range`` NOT NULL defaults false and ``provisional`` NOT NULL
defaults false: a report is trustworthy and in-range unless the compute
actively says otherwise, so the honest-but-degraded states must be set, never
assumed.
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

revision: str = "0001_biomechanics_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("biomechanics_reports",)


def upgrade() -> None:
    op.create_table(
        "biomechanics_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # correlation_id IS the stroke id — it threads the whole pipeline.
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Shot context from M09, carried so a report is self-describing.
        sa.Column("shot_type", sa.Text, nullable=True),
        sa.Column("shot_confidence", sa.Float, nullable=True),
        sa.Column(
            "phase_boundaries",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("phase_method", sa.Text, nullable=True),
        # BM-01..BM-17 + their _confidence companions.
        sa.Column(
            "metrics",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # mean_pose_confidence, spatial_confidence, depth_estimated, flags, ...
        sa.Column(
            "quality",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("schema_version", sa.Text, nullable=False),
        # Set when any metric fell outside its physiological range — flagged
        # for review, NEVER a reason to reject the report.
        sa.Column(
            "out_of_expected_range",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "reviewed_by_human",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        # True when a precondition or degradation reduced trust in the report.
        sa.Column(
            "provisional",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "computed_at",
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
    op.create_index("ix_biomechanics_tenant", "biomechanics_reports", ["tenant_id"])
    op.create_index(
        "ix_biomechanics_player_history",
        "biomechanics_reports",
        ["person_id", sa.text("computed_at DESC")],
    )
    # The review queue: only outstanding out-of-range reports.
    op.create_index(
        "ix_biomechanics_review_queue",
        "biomechanics_reports",
        ["computed_at"],
        postgresql_where=sa.text("out_of_expected_range AND NOT reviewed_by_human"),
    )
    # Query reports by metric value.
    op.create_index(
        "ix_biomechanics_metrics_gin",
        "biomechanics_reports",
        ["metrics"],
        postgresql_using="gin",
    )
    # One report per stroke (idempotent re-delivery, NFR-M10-04).
    op.create_unique_constraint(
        "uq_biomechanics_correlation", "biomechanics_reports", ["tenant_id", "correlation_id"]
    )

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
    op.drop_table("biomechanics_reports")
