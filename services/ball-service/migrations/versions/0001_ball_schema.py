"""M08 ball-tracking schema: ball_runs (summary; the track lives in object storage).

Revision ID: 0001_ball_schema
Revises:
Create Date: 2026-07-24

Creates the ball-service table per M08 §9. Depends on the M01 base migration
(``tenants`` for the tenant FK; ``cip_app`` for grants).

Tenant-scoped RLS, artefact split and correlation-keyed idempotency all follow
M05/M06/M07. What is different here is that a run may legitimately contain
NOTHING: M08 is the fail-safe module (NFR-M08-05), so a row with
``track_confidence`` low, ``timing_reference = 'absolute'`` and an empty
``events`` object is a valid, meaningful result — the clip was processed and
the honest answer is "the ball could not be tracked". The columns are shaped
so that state is representable without nulls standing in for it:

- ``events`` is JSONB and defaults to ``{}``, not null. Absent events are
  absent keys, never zeroed frame numbers.
- ``timing_reference`` is NOT NULL and defaults to ``absolute``, the safe
  value. A run must actively earn ``release_relative`` by detecting release;
  the default cannot silently promise M10 timing that was never established.
- ``conditions_met`` records whether the capture-condition gate passed, so a
  low-confidence run is distinguishable from a good-conditions run that
  simply had no ball in shot.
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

revision: str = "0001_ball_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("ball_runs",)


def upgrade() -> None:
    op.create_table(
        "ball_runs",
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
        # The pinned tracker that produced this run (registry version).
        sa.Column("model_version", sa.Text, nullable=False),
        # The labelled dataset that tracker was trained on (traceability).
        sa.Column("dataset_version", sa.Text, nullable=True),
        sa.Column("frame_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("frames_detected", sa.Integer, nullable=False, server_default=sa.text("0")),
        # Overall confidence in this delivery's tracking (0..1).
        sa.Column("track_confidence", sa.Float, nullable=False, server_default=sa.text("0")),
        # release_relative | absolute — defaults to the SAFE value.
        sa.Column(
            "timing_reference",
            sa.Text,
            nullable=False,
            server_default=sa.text("'absolute'"),
        ),
        # Did the capture-condition gate pass? Separates "bad clip" from
        # "good clip, no ball visible".
        sa.Column("conditions_met", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # release / bounce / contact + line / length / speed, each with its own
        # confidence. Absent events are absent keys.
        sa.Column(
            "events",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # ok | provisional | rejected
        sa.Column("quality", sa.Text, nullable=False),
        # Object-storage key of the full ball-track artefact.
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
    op.create_index("ix_ball_runs_tenant", "ball_runs", ["tenant_id"])
    # One ball run per clip (idempotent re-delivery, NFR-M08-04).
    op.create_unique_constraint(
        "uq_ball_runs_correlation", "ball_runs", ["tenant_id", "correlation_id"]
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
    op.drop_table("ball_runs")
