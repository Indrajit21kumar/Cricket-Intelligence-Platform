"""M07 bat-detection schema: bat_runs (compact index; bat track lives in object storage).

Revision ID: 0001_bat_schema
Revises:
Create Date: 2026-07-24

Creates the bat-service table per M07 §9. Depends on the M01 base migration
(``tenants`` for the tenant FK; ``cip_app`` for grants).

Same artefact split as M05/M06: the per-frame bat-keypoint sequence is written
to object storage and referenced by correlation_id, while the DB keeps a
compact, queryable summary.

Tenant-scoped RLS: M07 operates on tenant/player-namespaced video (§12), so
every row carries ``tenant_id`` under the M01 tenant_isolation policy.
``correlation_id`` threads the clip from M05 through the vision stack and is
the idempotency anchor — one bat run per clip (NFR-M07-04).

Two columns exist because M07 is data-gated in a way M06 is not:
``dataset_version`` records which labelled corpus the detector was trained on,
so a run is always traceable to its training data (§9, ENG-007); and
``frames_detected`` is kept separate from ``frame_count`` because the ratio of
the two — not the mean confidence alone — is what drives the degradation rule
(FR-M07-05).
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

revision: str = "0001_bat_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("bat_runs",)


def upgrade() -> None:
    op.create_table(
        "bat_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Threads the clip through the pipeline (from M05's video.normalized).
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The pinned detector that produced this run (registry version).
        sa.Column("model_version", sa.Text, nullable=False),
        # The labelled dataset that detector was trained on (traceability).
        sa.Column("dataset_version", sa.Text, nullable=True),
        sa.Column("frame_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        # Frames in which the bat was actually found — drives degradation.
        sa.Column("frames_detected", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("mean_confidence", sa.Float, nullable=True),
        # True when detection was too poor to trust downstream (FR-M07-05).
        sa.Column("provisional", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # ok | provisional | rejected — the overall bat-run quality.
        sa.Column("quality", sa.Text, nullable=False),
        # Object-storage key of the full bat-track artefact.
        sa.Column("artefact_ref", sa.Text, nullable=True),
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
    op.create_index("ix_bat_runs_tenant", "bat_runs", ["tenant_id"])
    # One bat run per clip (idempotent re-delivery, NFR-M07-04).
    op.create_unique_constraint(
        "uq_bat_runs_correlation", "bat_runs", ["tenant_id", "correlation_id"]
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
    op.drop_table("bat_runs")
