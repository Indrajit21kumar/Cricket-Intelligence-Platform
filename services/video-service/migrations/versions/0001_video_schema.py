"""M05 video-intelligence schema: ingestions, processing_results, calibrations, quality_flags.

Revision ID: 0001_video_schema
Revises:
Create Date: 2026-07-23

Creates the video-service tables per M05 §9. Depends on the M01 base
migration (``tenants`` must exist for the tenant FKs; ``cip_app`` role for
grants).

M05 is back to the tenant-scoped RLS model (unlike M04's person-anchored
profiles): raw + normalised video is stored per tenant/player namespace
(NFR-M05-04), so every table carries ``tenant_id`` and is governed by the
M01 ``tenant_isolation`` RLS policy. ``correlation_id`` threads one clip
through the whole pipeline (validate -> preprocess -> gate -> publish) and
is the idempotency anchor for safe re-delivery (NFR-M05-05).
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

revision: str = "0001_video_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = (
    "ingestions",
    "processing_results",
    "calibrations",
    "quality_flags",
)


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
    # --- ingestions (one row per uploaded clip) ----------------------------
    op.create_table(
        "ingestions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Player the clip is of (M02 person). Opaque UUID — no cross-service FK.
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Threads the clip through the whole pipeline + idempotency anchor.
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("source_type", sa.Text, nullable=False),  # mobile | dslr | nets | match
        sa.Column("raw_ref", sa.Text, nullable=True),  # object-storage key for the raw upload
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'created'"),
        ),  # created | uploaded | processing | normalized | rejected | failed
        sa.Column("content_type", sa.Text, nullable=True),
        sa.Column("size_bytes", sa.BigInteger, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_ingestions_tenant", "ingestions", ["tenant_id"])
    op.create_index("ix_ingestions_person", "ingestions", ["person_id"])
    # Idempotent processing per clip (NFR-M05-05): one ingestion per correlation.
    op.create_unique_constraint(
        "uq_ingestions_correlation", "ingestions", ["tenant_id", "correlation_id"]
    )

    # --- processing_results (preprocessing output refs) --------------------
    op.create_table(
        "processing_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_ref", sa.Text, nullable=True),  # normalised clip storage key
        sa.Column("frame_count", sa.Integer, nullable=True),
        sa.Column("fps", sa.Float, nullable=True),
        sa.Column("width", sa.Integer, nullable=True),
        sa.Column("height", sa.Integer, nullable=True),
        sa.Column("duration_s", sa.Float, nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_processing_ingestion", "processing_results", ["ingestion_id"])
    op.create_unique_constraint("uq_processing_ingestion", "processing_results", ["ingestion_id"])

    # --- calibrations (Book 4 Ch. 2 envelope) ------------------------------
    op.create_table(
        "calibrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("pixel_to_meter", sa.Float, nullable=True),
        sa.Column("camera_angle", sa.Text, nullable=True),  # side_on | front_on | square | other
        sa.Column(
            "spatial_confidence", sa.Text, nullable=False, server_default=sa.text("'low'")
        ),  # high | medium | low
        sa.Column("depth_estimated", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("method", sa.Text, nullable=True),  # 'stump' | 'height' | 'none'
        *_timestamps(),
    )
    op.create_index("ix_calibrations_ingestion", "calibrations", ["ingestion_id"])
    op.create_unique_constraint("uq_calibrations_ingestion", "calibrations", ["ingestion_id"])

    # --- quality_flags (gate decisions: fail/flag) -------------------------
    op.create_table(
        "quality_flags",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text, nullable=False),  # e.g. 'resolution_too_low'
        sa.Column("severity", sa.Text, nullable=False),  # 'fail' | 'flag'
        sa.Column("message", sa.Text, nullable=False),  # actionable, user-facing
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_quality_flags_ingestion", "quality_flags", ["ingestion_id"])

    # --- RLS on every table (tenant isolation) -----------------------------
    for table in TENANT_SCOPED_TABLES:
        for stmt in enable_rls_statements(table):
            op.execute(stmt)
        op.execute(tenant_isolation_policy_sql(table))

    # --- grants to the app role -------------------------------------------
    for table in TENANT_SCOPED_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    for table in TENANT_SCOPED_TABLES:
        op.execute(drop_tenant_isolation_policy_sql(table))
        for stmt in disable_rls_statements(table):
            op.execute(stmt)

    op.drop_table("quality_flags")
    op.drop_table("calibrations")
    op.drop_table("processing_results")
    op.drop_table("ingestions")
