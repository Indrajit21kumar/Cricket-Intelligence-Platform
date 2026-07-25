"""M09 shot-recognition schema: shot_runs (compact; no large artefact).

Revision ID: 0001_shot_schema
Revises:
Create Date: 2026-07-24

Creates the shot-service table per M09 §9. Depends on the M01 base migration
(``tenants`` for the tenant FK; ``cip_app`` for grants).

Unlike the perception modules (M06-M08), M09's output is small — a class, a
confidence, five phase boundaries — so it lives entirely in the DB with no
object-storage artefact (§9). Same tenant-scoped RLS and correlation-keyed
idempotency as the rest of the vision stack.

Two columns encode M09's honesty requirements directly:

- ``shot_class`` is NOT NULL and defaults to ``'unclassified'``. Abstention is
  a first-class outcome (FR-M09-02), not a null: a low-confidence stroke is
  positively marked unclassified so M10 applies generic handling rather than
  discovering a missing class. A run must EARN a real class.
- ``phase_method`` is NOT NULL and defaults to ``'bat_only_fallback'``, the
  weaker method. Standard segmentation must be earned by having usable ball
  events; the default cannot silently claim M08 anchored the impact when it
  did not (AC-M09-04).
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

revision: str = "0001_shot_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("shot_runs",)


def upgrade() -> None:
    op.create_table(
        "shot_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Threads the stroke through the pipeline (from M06's pose.keypoints).
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The pinned classifier that produced this run (registry version).
        sa.Column("model_version", sa.Text, nullable=False),
        # The labelled dataset that classifier was trained on (traceability).
        sa.Column("dataset_version", sa.Text, nullable=True),
        # One of the v1 taxonomy, or 'unclassified' — abstention is explicit.
        sa.Column(
            "shot_class",
            sa.Text,
            nullable=False,
            server_default=sa.text("'unclassified'"),
        ),
        sa.Column("shot_confidence", sa.Float, nullable=False, server_default=sa.text("0")),
        # Frame indices for stance/backlift/downswing/impact/follow_through.
        sa.Column(
            "phase_boundaries",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # standard (ball-anchored) | bat_only_fallback — defaults to the weaker.
        sa.Column(
            "phase_method",
            sa.Text,
            nullable=False,
            server_default=sa.text("'bat_only_fallback'"),
        ),
        # Which upstream signals fed the classification (pose | pose+bat | ...).
        sa.Column("signals_used", postgresql.JSONB, nullable=True),
        # ok | provisional | unclassified — the run-level quality.
        sa.Column("quality", sa.Text, nullable=False),
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
    op.create_index("ix_shot_runs_tenant", "shot_runs", ["tenant_id"])
    # One shot run per stroke (idempotent re-delivery, NFR-M09-03).
    op.create_unique_constraint(
        "uq_shot_runs_correlation", "shot_runs", ["tenant_id", "correlation_id"]
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
    op.drop_table("shot_runs")
