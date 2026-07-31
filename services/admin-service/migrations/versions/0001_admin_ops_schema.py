"""M20 admin ops schema: moderation_cases, review_queue, admin_actions.

Revision ID: 0001_admin_ops_schema
Revises:
Create Date: 2026-07-31

Creates the admin-service ops tables per M20 §9. Depends on the M01 base
migration only (for the ``cip_app`` role that grants target).

Global, not tenant-scoped
-------------------------
M20 is the platform's own operations backbone: an admin's job is inherently
cross-tenant (moderating any tenant's content, resolving any tenant's
flagged biomechanics samples, auditing any admin's actions). None of these
three tables carry RLS — the same RLS-free + app-layer-access pattern M12
established for its platform-global tables. Access control is RBAC
(``platform_admin`` only, enforced at the API layer from Step 2) plus the
fact that every privileged action against them is itself audited into
``admin_actions`` (and, per FR-M20-09, into M01's shared ``audit_log`` too).
All DB access is via ``admin_session`` (``cip_app`` sees every row in a
no-RLS table).

``moderation_cases`` and ``review_queue`` DO carry a ``tenant_id`` column
(the content/stroke they reference lives in a tenant), but it is descriptive
metadata for the admin's context switch and cross-tenant-access logging
(NFR-M20-02) — not an RLS scope, since an admin's whole job is to see across
tenants.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_admin_ops_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ADMIN_TABLES = ("moderation_cases", "review_queue", "admin_actions")


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    # --- moderation_cases: flagged content/clips under human review --------
    op.create_table(
        "moderation_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        # e.g. "video:<ingestion_id>" — mirrors audit_log's entity convention.
        sa.Column("subject_ref", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'open'")),
        sa.Column("action", sa.Text, nullable=True),
        sa.Column("actioned_by", sa.Text, nullable=True),
        sa.Column("actioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('open', 'actioned', 'dismissed')", name="ck_moderation_cases_status"
        ),
        *_timestamps(),
    )
    op.create_index(
        "ix_moderation_cases_open",
        "moderation_cases",
        ["created_at"],
        postgresql_where=sa.text("status = 'open'"),
    )

    # --- review_queue: out-of-range biomechanics samples awaiting a human ---
    # (FR-M20-06, mirrors the flag M10 Step 6 already computes per report —
    # this table is M20's own curated queue, populated from that source.)
    op.create_table(
        "review_queue",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stroke_ref", sa.Text, nullable=False),  # biomechanics correlation_id
        sa.Column("reason", sa.Text, nullable=False),  # flagged metric ids, comma-joined
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("reviewer", sa.Text, nullable=True),
        sa.Column("resolution_note", sa.Text, nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('pending', 'resolved')", name="ck_review_queue_status"),
        *_timestamps(),
    )
    # One queue row per flagged stroke — re-flagging the same stroke updates
    # the existing row rather than duplicating it.
    op.create_unique_constraint(
        "uq_review_queue_tenant_stroke", "review_queue", ["tenant_id", "stroke_ref"]
    )
    op.create_index(
        "ix_review_queue_pending",
        "review_queue",
        ["created_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )

    # --- admin_actions: privileged-action audit, IN ADDITION to audit_log ---
    # (FR-M20-09; the M01 audit_log record stays the platform-wide ledger,
    # this table is the admin-console-specific view used for its own
    # dashboards/search without querying a table this service doesn't own.)
    op.create_table(
        "admin_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("admin_ref", sa.Text, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        # NULL = a platform-wide action (not scoped to one tenant).
        sa.Column("tenant_ref", postgresql.UUID(as_uuid=True), nullable=True),
        # Cross-tenant access is inherent to this role; this flag makes it
        # queryable directly rather than inferred from tenant_ref (NFR-M20-02).
        sa.Column("cross_tenant", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
    )
    op.create_index("ix_admin_actions_admin_ref", "admin_actions", ["admin_ref", "at"])
    op.create_index("ix_admin_actions_at", "admin_actions", ["at"])

    for table in ADMIN_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    op.drop_table("admin_actions")
    op.drop_table("review_queue")
    op.drop_table("moderation_cases")
