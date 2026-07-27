"""M12 evidence layer (Book 10): sources, rule_sources, + rule evidence fields.

Revision ID: 0002_evidence
Revises: 0001_knowledge_schema
Create Date: 2026-07-27

Adds the Evidence-Based Coaching Layer (Book 10) on top of the core graph:

- ``sources`` — a cited external authority (paper / manual / expert). A source
  must be SAB-vetted (``vetted_by`` set) before it can back a served rule.
- ``rule_sources`` — the Rule<->Source links, carrying the relation
  (``supported_by`` / ``contradicted_by``) and a locator (page/section).
- new columns on ``rules``: ``evidence_tier`` (1 validated / 2 consensus /
  3 folklore), ``contradicts_tradition`` (+ a note), ``evidence_last_reviewed``,
  and ``validated_by`` (the SAB reviewer + credential that signed the tier off).

The honesty rules these enable (enforced in the service): a rule with evidence
may only be released once its sources are vetted and its tier is signed off; a
Tier 2/3 rule is never presented as validated; and a tradition-contradicting
rule must carry its contradicting citation, never be silently dropped.

Global tables (coaching IP), so no RLS — access is RBAC + audit like the rest.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_evidence"
down_revision: str | Sequence[str] | None = "0001_knowledge_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVIDENCE_TABLES = ("sources", "rule_sources")


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Text, nullable=False),  # paper | manual | expert
        sa.Column("authors", sa.Text, nullable=True),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("authority", sa.Text, nullable=True),  # journal / body / person
        sa.Column("url_or_ref", sa.Text, nullable=True),
        sa.Column("license_note", sa.Text, nullable=True),
        # The SAB sign-off on the source itself: {reviewer, credential}. Until
        # set, the source is unvetted and cannot back a served rule.
        sa.Column("vetted_by", postgresql.JSONB, nullable=True),
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

    op.create_table(
        "rule_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.Text, nullable=False),  # supported_by | contradicted_by
        sa.Column("locator", sa.Text, nullable=True),  # page / section / timestamp
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_rule_sources_rule", "rule_sources", ["rule_id"])
    op.create_unique_constraint(
        "uq_rule_sources_link", "rule_sources", ["rule_id", "source_id", "relation"]
    )

    # --- evidence metadata on rules ---
    op.add_column("rules", sa.Column("evidence_tier", sa.Integer, nullable=True))
    op.add_column(
        "rules",
        sa.Column(
            "contradicts_tradition",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("rules", sa.Column("contradiction_note", sa.Text, nullable=True))
    op.add_column(
        "rules", sa.Column("evidence_last_reviewed", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("rules", sa.Column("validated_by", postgresql.JSONB, nullable=True))

    for table in EVIDENCE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    op.drop_column("rules", "validated_by")
    op.drop_column("rules", "evidence_last_reviewed")
    op.drop_column("rules", "contradiction_note")
    op.drop_column("rules", "contradicts_tradition")
    op.drop_column("rules", "evidence_tier")
    op.drop_table("rule_sources")
    op.drop_table("sources")
