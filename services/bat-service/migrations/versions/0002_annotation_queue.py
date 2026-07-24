"""M07 training-data flywheel: annotation_queue + annotation_datasets.

Revision ID: 0002_annotation_queue
Revises: 0001_bat_schema
Create Date: 2026-07-24

M07 §9 makes the training-data loop explicit: consented frames are routed for
labelling, labelled, frozen into a versioned corpus, and used to retrain the
detector — which ``bat_runs.dataset_version`` then points back at.

Two tables, deliberately different in scope:

``annotation_queue`` is tenant-scoped under RLS. It holds frames of real
players, so it is subject to exactly the same isolation as the clips it came
from — an academy can never see another academy's queued frames. Every row
records ``consent_reason``, the decision that admitted it, so an auditor can
answer "why is this child's frame in the corpus?" years later without
re-deriving consent state that may since have changed.

``annotation_datasets`` is the platform-level manifest of frozen corpora. It
carries no player data — only a version, a count and a checksum — so it is
global (admin-managed), like M03's plan catalogue.

Deletion note: withdrawing training consent must remove queued frames. The
FK to ``persons`` is intentionally omitted (that table is M02-owned and this
service must not reach across the boundary at write time); the withdrawal
path deletes by ``person_id`` instead, which the index below supports.
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

revision: str = "0002_annotation_queue"
down_revision: str | Sequence[str] | None = "0001_bat_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("annotation_queue",)


def upgrade() -> None:
    op.create_table(
        "annotation_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.Text, nullable=False),
        # Whose frame this is — the anchor for consent withdrawal + deletion.
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("frame_index", sa.Integer, nullable=False),
        # low_confidence | failed | sampled — why this frame is worth labelling.
        sa.Column("reason", sa.Text, nullable=False),
        # The detector's own guess, for the labeller to correct rather than
        # start from scratch. Never treated as ground truth.
        sa.Column("weak_label", postgresql.JSONB, nullable=True),
        # Which consent decision admitted this frame (training_consent |
        # guardian_consent) — the audit answer, recorded at admission time.
        sa.Column("consent_reason", sa.Text, nullable=False),
        # Set when the frame is frozen into a released corpus.
        sa.Column("dataset_version", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_annotation_queue_tenant", "annotation_queue", ["tenant_id"])
    op.create_index("ix_annotation_queue_person", "annotation_queue", ["person_id"])
    op.create_index("ix_annotation_queue_dataset", "annotation_queue", ["dataset_version"])
    # One queue row per (clip, frame) — re-running a clip must not re-queue it.
    op.create_unique_constraint(
        "uq_annotation_queue_frame",
        "annotation_queue",
        ["tenant_id", "correlation_id", "frame_index"],
    )

    op.create_table(
        "annotation_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # The version a detector cites in bat_runs.dataset_version.
        sa.Column("version", sa.Text, nullable=False, unique=True),
        sa.Column("item_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        # Content hash over the frozen item set — makes "same version" checkable.
        sa.Column("checksum", sa.Text, nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "frozen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Writes come from the ops/freeze path, which runs under admin_session —
    # and that still runs as cip_app, so the grant must cover DML. Who may
    # freeze a corpus is enforced by role at the API layer, not by table grant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON annotation_datasets TO cip_app")

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
    op.drop_table("annotation_datasets")
    op.drop_table("annotation_queue")
