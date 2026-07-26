"""M11 physics schema: physics_reports (one report per stroke).

Revision ID: 0001_physics_schema
Revises:
Create Date: 2026-07-26

Creates the physics-service table per M11 §11. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

M11's output is a compact per-stroke report — the PH-01..PH-11 quantities (each
with provenance + confidence), the kinetic-chain sequence, and a quality block
propagated from the M10 report — so it lives entirely in the DB, no object-
storage artefact. Tenant-scoped RLS, correlation-keyed idempotency (one report
per stroke).

Two auditability columns the trust doctrine requires:

- ``schema_version`` — the ``physics.metrics`` wire-contract version, so a
  consumer (M12/M13/M14/M15) knows the shape it is reading.
- ``model_version`` — the estimation-model version. Because PH-06..PH-11 are
  ESTIMATED through versioned models (§13, NFR-M11-04), every report records
  which model produced it; the Step 8 validation gate blocks an unvalidated or
  regressing model, and this column is how a shipped estimate is traced back.

Indexes carry §11's operational needs:

- ``(person_id, computed_at DESC)`` — a player's physics history, newest first.
- a PARTIAL index over the review queue: rows flagged
  ``out_of_expected_range`` a human has not yet reviewed. Partial so the index
  indexes only the outstanding work.
- a GIN index on the ``quantities`` JSONB, so M15/M12 can query by physics value
  (e.g. "strokes where PH-10 ball-exit > 30 m/s") without a full scan.

``out_of_expected_range`` and ``provisional`` NOT NULL default false: a report
is trustworthy and in-range unless the compute actively says otherwise, so the
honest-but-degraded states must be set, never assumed.
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

revision: str = "0001_physics_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("physics_reports",)


def upgrade() -> None:
    op.create_table(
        "physics_reports",
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
        # Shot context carried from M09/M10 so a report is self-describing for
        # the M14 narrative ("cover drive: ball-exit ~28 m/s").
        sa.Column("shot_type", sa.Text, nullable=True),
        sa.Column("shot_confidence", sa.Float, nullable=True),
        # PH-01..PH-11, each: value + provenance (measured/estimated) +
        # confidence (mandatory on every estimate).
        sa.Column(
            "quantities",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Energy-transfer sequence feet->knee->hip->shoulder->hands->bat + the
        # identified loss points (ESTIMATED).
        sa.Column(
            "kinetic_chain",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Quality block propagated from the M10 report (spatial/depth confidence,
        # provisional, flags) + the mass-estimate uncertainty M11 adds.
        sa.Column(
            "quality",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # The physics.metrics wire-contract version.
        sa.Column("schema_version", sa.Text, nullable=False),
        # The estimation-model version — every ESTIMATED quantity is traceable
        # to the model that produced it (§13, NFR-M11-04).
        sa.Column("model_version", sa.Text, nullable=False),
        # Set when any quantity fell outside its expected range — flagged for
        # review, NEVER a reason to reject the report.
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
        # True when the M10 report was provisional (its degradation propagates).
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
    op.create_index("ix_physics_tenant", "physics_reports", ["tenant_id"])
    op.create_index(
        "ix_physics_player_history",
        "physics_reports",
        ["person_id", sa.text("computed_at DESC")],
    )
    # The review queue: only outstanding out-of-range reports.
    op.create_index(
        "ix_physics_review_queue",
        "physics_reports",
        ["computed_at"],
        postgresql_where=sa.text("out_of_expected_range AND NOT reviewed_by_human"),
    )
    # Query reports by physics value.
    op.create_index(
        "ix_physics_quantities_gin",
        "physics_reports",
        ["quantities"],
        postgresql_using="gin",
    )
    # One report per stroke (idempotent re-delivery, NFR-M11-03).
    op.create_unique_constraint(
        "uq_physics_correlation", "physics_reports", ["tenant_id", "correlation_id"]
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
    op.drop_table("physics_reports")
