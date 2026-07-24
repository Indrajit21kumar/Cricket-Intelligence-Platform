"""M06 pose-engine schema: pose_runs (compact index; keypoints live in object storage).

Revision ID: 0001_pose_schema
Revises:
Create Date: 2026-07-24

Creates the pose-service table per M06 §9. Depends on the M01 base migration
(``tenants`` for the tenant FK; ``cip_app`` for grants).

Keypoint sequences are large, so the full per-frame payload is stored as an
ARTEFACT in object storage (referenced by correlation_id); the DB keeps only a
compact, queryable summary. Same artefact pattern as M05.

Tenant-scoped RLS: pose runs operate on tenant/player-namespaced video
(§12), so every row carries ``tenant_id`` under the M01 tenant_isolation
policy. ``correlation_id`` threads the clip from M05 through M06 and is the
idempotency anchor (one pose run per clip, NFR-M06-04).
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

revision: str = "0001_pose_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("pose_runs",)


def upgrade() -> None:
    op.create_table(
        "pose_runs",
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
        # The pinned pose model that produced this run (registry version).
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("frame_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("mean_confidence", sa.Float, nullable=True),
        # tracked | multi_subject_ambiguous | no_subject
        sa.Column("subject_status", sa.Text, nullable=False),
        # ok | provisional | rejected — the overall pose-run quality.
        sa.Column("quality", sa.Text, nullable=False),
        # Object-storage key of the full keypoint-sequence artefact.
        sa.Column("artefact_ref", sa.Text, nullable=True),
        sa.Column("depth_estimated", sa.Boolean, nullable=False, server_default=sa.text("false")),
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
    op.create_index("ix_pose_runs_tenant", "pose_runs", ["tenant_id"])
    # One pose run per clip (idempotent re-delivery, NFR-M06-04).
    op.create_unique_constraint(
        "uq_pose_runs_correlation", "pose_runs", ["tenant_id", "correlation_id"]
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
    op.drop_table("pose_runs")
