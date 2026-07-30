"""M15 benchmark schema: benchmark_profiles (global) + comparisons (tenant RLS).

Revision ID: 0001_benchmark_schema
Revises:
Create Date: 2026-07-30

Creates the benchmark-service tables per M15 §9. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

Two different scoping regimes in one service (a first for this build):

- ``benchmark_profiles`` is platform-GLOBAL, like M12's knowledge tables:
  benchmark profiles are Book 5 (CIBL) reference data, not personal data, so
  NO tenant_id and NO RLS. Access control is the "only released versions
  serve" rule enforced at the API/domain layer (NFR-M15-05, AC-M15-06), the
  same RLS-free + app-layer-access pattern M04/M12 established.
- ``comparisons`` is tenant-scoped with RLS + FORCE + tenant_isolation, like
  M10/M11/M13/M14: one player's comparison against a benchmark is personal
  data (§12).

``benchmark_profiles`` carries BOTH a stable ``benchmark_id`` (e.g.
``BN-TIER-ADV-COVERDRIVE``) and a ``version`` — releasing a new version never
mutates a served one, so a past comparison stays reproducible against the
exact profile it used (FR-M15-08, AC-M15-06). ``released`` gates what
``domain/profiles.py`` may select; unreleased profiles are invisible to
comparison, never partially trusted.

``comparisons.legend_similarity`` is shaped exactly like M14's
``LegendView.to_dict()`` (``{"styles": [...], "benchmark_version": ...}``),
so M14's ``LegendSource`` will read this column directly once a real
implementation replaces the current Fake.
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

revision: str = "0001_benchmark_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("comparisons",)


def upgrade() -> None:
    # --- benchmark_profiles: platform-global (Book 5 reference data) ---
    op.create_table(
        "benchmark_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Stable identifier, e.g. "BN-TIER-ADV-COVERDRIVE" (Book 5 Ch. 2).
        sa.Column("benchmark_id", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),  # skill_tier|age_band|legend_style|personal
        # Context: shot type / skill tier / age band / handedness (Book 5 Ch. 2).
        sa.Column("scope", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        # Per-metric (BM/PH) mean/spread/target-range distributions (M15 §9).
        sa.Column(
            "distributions",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("derivation_method", sa.Text, nullable=True),
        sa.Column("sample_size", sa.Integer, nullable=True),
        sa.Column("source", sa.Text, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("validation_ref", sa.Text, nullable=True),
        # Only released profiles may be selected for comparison (NFR-M15-05).
        sa.Column("released", sa.Boolean, nullable=False, server_default=sa.text("false")),
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
            "type IN ('skill_tier', 'age_band', 'legend_style', 'personal')",
            name="ck_benchmark_profiles_type",
        ),
    )
    op.create_index("ix_benchmark_profiles_type", "benchmark_profiles", ["type"])
    op.create_index(
        "ix_benchmark_profiles_released",
        "benchmark_profiles",
        ["benchmark_id"],
        postgresql_where=sa.text("released"),
    )
    # One profile per (benchmark_id, version) — versions are additive, not edits.
    op.create_unique_constraint(
        "uq_benchmark_profiles_id_version", "benchmark_profiles", ["benchmark_id", "version"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON benchmark_profiles TO cip_app")

    # --- comparisons: tenant-scoped, personal data ---
    op.create_table(
        "comparisons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # correlation_id IS the stroke id (M15 spec's "stroke_id").
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "per_metric", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        # Shaped like M14's LegendView.to_dict(): {"styles": [...], "benchmark_version": ...}.
        sa.Column(
            "legend_similarity",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        # The pinned benchmark_profiles version set used (FR-M15-08).
        sa.Column("benchmark_version", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("schema_version", sa.Text, nullable=False),
        sa.Column("provisional", sa.Boolean, nullable=False, server_default=sa.text("false")),
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
    op.create_index("ix_comparisons_tenant", "comparisons", ["tenant_id"])
    op.create_index(
        "ix_comparisons_player_history",
        "comparisons",
        ["person_id", sa.text("computed_at DESC")],
    )
    # One comparison per stroke (idempotent re-delivery, NFR-M15-03).
    op.create_unique_constraint(
        "uq_comparisons_correlation", "comparisons", ["tenant_id", "correlation_id"]
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
    op.drop_table("comparisons")
    op.drop_table("benchmark_profiles")
