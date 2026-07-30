"""M13 reasoning schema: reasoning_results + finding_evidence (one result per stroke).

Revision ID: 0001_reasoning_schema
Revises:
Create Date: 2026-07-27

Creates the reasoning-service tables per M13 §10. Depends on the M01 base
migration (``tenants`` for the tenant FK; ``cip_app`` for grants).

Reasoning results are PERSONAL DATA (§13) — they describe a specific player's
stroke — so unlike M12's global knowledge these tables are tenant-scoped with
RLS + FORCE + the tenant_isolation policy, exactly like M10/M11.

- ``reasoning_results`` — one row per stroke (correlation_id = stroke id). The
  findings + match_risk + quality live in JSONB, and ``kg_version`` pins the
  exact M12 rule version set used, so a past result is reproducible against the
  precise knowledge that produced it (FR-M13-10, AC-M13-07).
- ``finding_evidence`` — one row per (finding, evidence) so "how do you know?"
  is queryable both ways: a finding's evidence is embedded in the result JSONB,
  and this table indexes the reverse (which findings a given rule produced), the
  backbone of explainability (ENG-005).

``provisional`` NOT NULL defaults false: a result is trustworthy unless a
provisional input said otherwise.
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

revision: str = "0001_reasoning_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_SCOPED_TABLES = ("reasoning_results", "finding_evidence")


def upgrade() -> None:
    op.create_table(
        "reasoning_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # correlation_id IS the stroke id — it threads the whole pipeline.
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Shot context (from M09), carried so a result is self-describing.
        sa.Column("shot_type", sa.Text, nullable=True),
        sa.Column("shot_confidence", sa.Float, nullable=True),
        # The pinned M12 knowledge version used — reproducibility (FR-M13-10).
        sa.Column("kg_version", sa.Text, nullable=False),
        # The explained findings: [{what, why, impact, drill, evidence[], ...}].
        sa.Column(
            "findings",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        # Contextual match risk (MODELLED), where rules provided it.
        sa.Column(
            "match_risk",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "quality",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("schema_version", sa.Text, nullable=False),
        # True when the result rests on provisional inputs (propagated).
        sa.Column(
            "provisional",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
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
    op.create_index("ix_reasoning_tenant", "reasoning_results", ["tenant_id"])
    op.create_index(
        "ix_reasoning_player_history",
        "reasoning_results",
        ["person_id", sa.text("computed_at DESC")],
    )
    # One result per stroke (idempotent re-delivery, NFR-M13-03).
    op.create_unique_constraint(
        "uq_reasoning_correlation", "reasoning_results", ["tenant_id", "correlation_id"]
    )

    op.create_table(
        "finding_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reasoning_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The finding this evidence belongs to (its id within the result).
        sa.Column("finding_ref", sa.Text, nullable=False),
        # The BM/PH metric ids that triggered the finding.
        sa.Column(
            "metric_ids",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("rule_version", sa.Integer, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_finding_evidence_result", "finding_evidence", ["result_id"])
    # Reverse lookup: which findings a given rule version produced (explainability).
    op.create_index("ix_finding_evidence_rule", "finding_evidence", ["rule_id", "rule_version"])

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
    op.drop_table("finding_evidence")
    op.drop_table("reasoning_results")
