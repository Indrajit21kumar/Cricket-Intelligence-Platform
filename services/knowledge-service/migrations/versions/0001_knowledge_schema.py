"""M12 knowledge-graph schema: entities, relationships, rules, versions, conflicts.

Revision ID: 0001_knowledge_schema
Revises:
Create Date: 2026-07-27

Creates the knowledge-service tables per M12 §10. Depends on the M01 base
migration only (for the ``cip_app`` role that grants target).

Global, not tenant-scoped
-------------------------
The knowledge graph is coaching IP, not personal data (§13), so it is
platform-GLOBAL: NONE of these tables carry ``tenant_id`` and NONE get row-level
security. Access control is instead RBAC at the API layer (authoring is
restricted to the M12 governance roles) and every change is audited — the same
RLS-free + app-layer-access pattern M04 established for its portable tables.
All DB access is via ``admin_session`` (``cip_app`` sees every row in a no-RLS
table).

The lifecycle (§12) is ``draft -> in_review -> approved -> released ->
superseded``. ``rules`` holds one row per (rule_id, version) carrying its
current ``status``; ``rule_versions`` holds the immutable snapshot per version
and the ``released`` pin, so a past report can always be reproduced against the
exact rule version that produced it (AC-M12-03). The evidence layer (sources,
rule_sources, evidence_tier/validated_by — Book 10) is added by a later
migration (Step 8), keeping this first migration the canonical core.

Indexes are tuned for the fact-pattern lookup M13 makes (NFR-M12-01): a GIN
index over ``rules.conditions`` plus a partial index over the released rules.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_knowledge_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# All M12 tables are global (coaching IP). No RLS — access control is RBAC at
# the API layer + audit.
KNOWLEDGE_TABLES = (
    "entities",
    "relationships",
    "rules",
    "rule_versions",
    "rule_conflicts",
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
    # --- entities: ontology instances (shots, faults, causes, risks, drills) --
    op.create_table(
        "entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Text, nullable=False),  # Shot | Phase | Metric | Fault | ...
        sa.Column("key", sa.Text, nullable=False),  # stable slug, unique within a type
        sa.Column("attrs", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_entities_type", "entities", ["type"])
    op.create_unique_constraint("uq_entities_type_key", "entities", ["type", "key"])

    # --- relationships: typed edges between entities -------------------------
    op.create_table(
        "relationships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "from_entity",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rel_type", sa.Text, nullable=False
        ),  # indicates | caused_by | corrected_by | ...
        sa.Column(
            "to_entity",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attrs", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        *_timestamps(),
    )
    op.create_index("ix_relationships_from", "relationships", ["from_entity", "rel_type"])
    op.create_index("ix_relationships_to", "relationships", ["to_entity", "rel_type"])
    op.create_unique_constraint(
        "uq_relationships_edge", "relationships", ["from_entity", "rel_type", "to_entity"]
    )

    # --- rules: canonical Fault->Cause->Risk->Drill + governance metadata ----
    op.create_table(
        "rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # The stable, human-facing rule id (e.g. 'KG-RISK-002'); many versions.
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        # Conditions matched against a stroke's facts (metric thresholds / phase
        # facts / shot / context). GIN-indexed for the M13 fact-pattern lookup.
        sa.Column(
            "conditions", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("fault", sa.Text, nullable=True),
        sa.Column("cause", sa.Text, nullable=True),
        # risk carries context (Delivery) + magnitude; drill carries a
        # measurable objective — both structured, hence JSONB.
        sa.Column("risk", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("drill", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("confidence", sa.Float, nullable=True),  # authored 0..1 (Trust Doctrine)
        # Lifecycle status: draft | in_review | approved | released | superseded.
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'draft'")),
        sa.Column("author", sa.Text, nullable=True),
        sa.Column("reviewer", sa.Text, nullable=True),
        *_timestamps(),
    )
    op.create_unique_constraint("uq_rules_rule_id_version", "rules", ["rule_id", "version"])
    op.create_index("ix_rules_status", "rules", ["status"])
    op.create_index("ix_rules_rule_id", "rules", ["rule_id"])
    # Fact-pattern lookup: GIN over the conditions document (NFR-M12-01).
    op.create_index("ix_rules_conditions_gin", "rules", ["conditions"], postgresql_using="gin")
    # The served set is the released rules — a small, hot partial index.
    op.create_index(
        "ix_rules_released",
        "rules",
        ["rule_id"],
        postgresql_where=sa.text("status = 'released'"),
    )

    # --- rule_versions: immutable snapshot per version + release pin ---------
    op.create_table(
        "rule_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        # The full frozen rule as released — the record a past report cites.
        sa.Column(
            "snapshot", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column("released", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_unique_constraint(
        "uq_rule_versions_rule_id_version", "rule_versions", ["rule_id", "version"]
    )
    op.create_index(
        "ix_rule_versions_released",
        "rule_versions",
        ["rule_id"],
        postgresql_where=sa.text("released"),
    )

    # --- rule_conflicts: recorded precedence for rules that co-fire ----------
    op.create_table(
        "rule_conflicts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("rule_a", sa.Text, nullable=False),
        sa.Column("rule_b", sa.Text, nullable=False),
        # Which rule_id wins when both match the same facts (recorded precedence).
        sa.Column("precedence", sa.Text, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("resolved", sa.Boolean, nullable=False, server_default=sa.text("false")),
        *_timestamps(),
    )
    op.create_unique_constraint("uq_rule_conflicts_pair", "rule_conflicts", ["rule_a", "rule_b"])

    # --- grants to the app role (no RLS: access control is RBAC + audit) -----
    for table in KNOWLEDGE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    op.drop_table("rule_conflicts")
    op.drop_table("rule_versions")
    op.drop_table("rules")
    op.drop_table("relationships")
    op.drop_table("entities")
