"""M14 report schema: reports, coach_sessions, coach_messages.

Revision ID: 0001_report_schema
Revises:
Create Date: 2026-07-27

Creates the report-service tables per M14 §11. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

Reports and coach conversations are PERSONAL DATA (§13) — tenant-scoped with
RLS + FORCE + tenant_isolation, exactly like M10/M11/M13.

- ``reports`` — one row per stroke (correlation_id = stroke id). ``structure``
  holds the whole assembled report (scores, findings, metric panels, legend
  view); ``kg_version`` + the M13 result it narrates make the report
  reproducible (NFR-M14-03, AC-M14-07).
- ``coach_sessions`` — one AI Coach conversation per row, anchored to a player.
- ``coach_messages`` — each Q&A turn, with ``citations`` (the evidence the
  answer grounded on) so every coach reply is auditable (§13, AC-M14-03).

``schema_version`` stamps the wire contract; ``annotated_video_ref`` is an
opaque object-storage pointer, not raw video.
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

revision: str = "0001_report_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("reports", "coach_sessions", "coach_messages")


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # correlation_id IS the stroke id — the M13 result this report narrates.
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # The pinned M12 knowledge version the underlying findings used.
        sa.Column("kg_version", sa.Text, nullable=False),
        # The full assembled report: scores, findings, metric panels, legend view.
        sa.Column(
            "structure",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # Overall + sub-scores (Book 4 Ch. 8).
        sa.Column(
            "scores",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("annotated_video_ref", sa.Text, nullable=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column(
            "provisional",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
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
    op.create_index("ix_reports_tenant", "reports", ["tenant_id"])
    op.create_index(
        "ix_reports_player_history",
        "reports",
        ["person_id", sa.text("created_at DESC")],
    )
    # One report per stroke (idempotent re-delivery).
    op.create_unique_constraint(
        "uq_reports_correlation", "reports", ["tenant_id", "correlation_id"]
    )

    op.create_table(
        "coach_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_coach_sessions_tenant", "coach_sessions", ["tenant_id"])
    op.create_index("ix_coach_sessions_person", "coach_sessions", ["person_id"])

    op.create_table(
        "coach_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "coach_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("coach_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.Text, nullable=False),  # user | coach
        sa.Column("content", sa.Text, nullable=False),
        # The evidence (finding/rule/metric ids) the reply grounded on. Empty for
        # a deferred/refused answer — there is nothing to cite.
        sa.Column(
            "citations",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "deferred",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_coach_messages_tenant", "coach_messages", ["tenant_id"])
    op.create_index("ix_coach_messages_session", "coach_messages", ["coach_session_id"])

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
    op.drop_table("coach_messages")
    op.drop_table("coach_sessions")
    op.drop_table("reports")
