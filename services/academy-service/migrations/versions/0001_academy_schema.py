"""M18 academy schema: academy_sessions, session_players, coach_assignments, shared_reports.

Revision ID: 0001_academy_schema
Revises:
Create Date: 2026-07-31

Creates the academy-service tables per M18 §9. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

All four tables are tenant-scoped with RLS + FORCE + tenant_isolation, like
every other tenant-owned table in this build (M18 §9: "All tenant-scoped
with row-level security"). M18 does not duplicate player analysis data —
``coach_ref``/``player_ref`` are plain UUIDs with NO cross-service FK
(service-boundary hygiene, the same pattern M04/M10-M17 all use for
person_id), resolved against M02/M04/M14/M16/M17 at read time via source
adapters, not stored here.

``coach_assignments.active`` is a soft flag, not a delete: unassigning a
coach is append-only history (deactivate, never destroy), the same pattern
every longitudinal table in this build follows. Portability (FR-M18-07) is
enforced independently at read time by checking LIVE M02 membership, not by
this table's state — a stale assignment row never grants access on its own.
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

revision: str = "0001_academy_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = (
    "academy_sessions",
    "session_players",
    "coach_assignments",
    "shared_reports",
)


def upgrade() -> None:
    op.create_table(
        "academy_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("coach_ref", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'scheduled'")),
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
            "status IN ('scheduled', 'completed', 'cancelled')", name="ck_academy_sessions_status"
        ),
    )
    op.create_index("ix_academy_sessions_tenant", "academy_sessions", ["tenant_id"])
    op.create_index(
        "ix_academy_sessions_coach", "academy_sessions", ["tenant_id", "coach_ref", "scheduled_at"]
    )

    op.create_table(
        "session_players",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("academy_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("player_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attended", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # A linked analysis (M05 correlation_id / M14 report ref), if any.
        sa.Column("analysis_ref", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_session_players_session", "session_players", ["session_id"])
    op.create_unique_constraint(
        "uq_session_players_session_player", "session_players", ["session_id", "player_ref"]
    )

    op.create_table(
        "coach_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("coach_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("player_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
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
    op.create_index("ix_coach_assignments_coach", "coach_assignments", ["tenant_id", "coach_ref"])
    op.create_index("ix_coach_assignments_player", "coach_assignments", ["tenant_id", "player_ref"])
    op.create_unique_constraint(
        "uq_coach_assignments_pair", "coach_assignments", ["tenant_id", "coach_ref", "player_ref"]
    )

    op.create_table(
        "shared_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("report_ref", sa.Text, nullable=False),
        # e.g. "guardian:<uuid>" / "coach:<uuid>" — flexible recipient identifier.
        sa.Column("shared_with", sa.Text, nullable=False),
        sa.Column("shared_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "shared_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_shared_reports_report", "shared_reports", ["tenant_id", "report_ref"])

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
    op.drop_table("shared_reports")
    op.drop_table("coach_assignments")
    op.drop_table("session_players")
    op.drop_table("academy_sessions")
