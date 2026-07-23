"""M04 player-profile schema: profiles, DNA traits + history, snapshots, history index, baselines.

Revision ID: 0001_profile_schema
Revises:
Create Date: 2026-07-23

Creates the profile-service tables per M04 §9. Depends on the M01 base
migration only (for the ``cip_app`` role that grants target).

Table ownership + the person-anchor decision
---------------------------------------------
Unlike M02/M03, these tables are **person-anchored, not tenant-owned**
(ENG-002 portability: a player's technical history must survive changing
academies). So:

- NONE of these tables carry ``tenant_id`` and NONE get row-level security.
  Tenant-scoped *visibility* is enforced at the application layer via the
  M02 consent + membership check (shared ``cip_core`` helper), NOT by owning
  the row inside a tenant. Leaving a tenant removes access, never the row
  (NFR-M04-04).
- ``player_profiles.person_id`` is a plain indexed UUID, deliberately WITHOUT
  a database FK to M02's ``persons`` table. A hard cross-service FK would
  couple profile-service's schema to identity-service's and break the day
  the two get separate databases (ENG-004 boundary rule). The 1:1 link to a
  real person is enforced on the write path, not by a constraint. FKs
  *within* this service (profile_id -> player_profiles) are real.

Trust Doctrine (Book 0 §8): every trait value is a computed analytical
quantity, so ``dna_traits`` + ``dna_trait_history`` carry ``provenance``
(measured|estimated|modelled) + ``confidence``. Attributes (height, stance,
age band) are declared inputs, not computed outputs, so they don't.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_profile_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# All M04 tables are global (person-anchored). No RLS — access control is the
# consent helper at the app layer.
PROFILE_TABLES = (
    "player_profiles",
    "dna_traits",
    "dna_trait_history",
    "dna_snapshots",
    "history_index",
    "personal_baselines",
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
    # --- player_profiles (1:1 with an M02 person) --------------------------
    op.create_table(
        "player_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Anchor to the global person. Indexed UUID, no cross-service FK.
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("height_cm", sa.Integer, nullable=True),  # anthropometric input for M10
        sa.Column("stance", sa.Text, nullable=True),  # 'right-hand-bat' | 'left-hand-bat'
        sa.Column("age_band", sa.Text, nullable=True),  # 'u13' | 'u16' | 'u19' | 'senior'
        sa.Column("dominant_hand", sa.Text, nullable=True),  # 'right' | 'left'
        *_timestamps(),
    )
    # One profile per person (1:1).
    op.create_unique_constraint("uq_player_profiles_person", "player_profiles", ["person_id"])

    # --- dna_traits (current value per trait) ------------------------------
    op.create_table(
        "dna_traits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("player_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trait_key", sa.Text, nullable=False),  # 'trait.aggression', 'style.stance', ...
        sa.Column("value", sa.Text, nullable=False),  # stringified score/label (trait-typed)
        sa.Column("confidence", sa.Float, nullable=True),  # 0..1 (Trust Doctrine)
        sa.Column(
            "provenance",
            sa.Text,
            nullable=False,
            server_default=sa.text("'modelled'"),
        ),  # measured | estimated | modelled
        sa.Column("source_ref", sa.Text, nullable=True),  # e.g. 'report:<uuid>' from M16
        *_timestamps(),
    )
    op.create_index("ix_dna_traits_profile", "dna_traits", ["profile_id"])
    # One current value per (profile, trait); history keeps the rest.
    op.create_unique_constraint(
        "uq_dna_traits_profile_key", "dna_traits", ["profile_id", "trait_key"]
    )

    # --- dna_trait_history (append-only, NFR-M04-02) -----------------------
    op.create_table(
        "dna_trait_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("player_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trait_key", sa.Text, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column(
            "provenance",
            sa.Text,
            nullable=False,
            server_default=sa.text("'modelled'"),
        ),
        sa.Column("source_ref", sa.Text, nullable=True),
        sa.Column(
            "snapshot_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    # Reconstruct any trait's value as of any point in time.
    op.create_index(
        "ix_dna_trait_history_lookup",
        "dna_trait_history",
        ["profile_id", "trait_key", "snapshot_at"],
    )

    # --- dna_snapshots (versioned point-in-time full DNA) ------------------
    op.create_table(
        "dna_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("player_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column(
            "taken_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index("ix_dna_snapshots_profile", "dna_snapshots", ["profile_id"])
    op.create_unique_constraint(
        "uq_dna_snapshots_profile_version", "dna_snapshots", ["profile_id", "version"]
    )

    # --- history_index (links profile -> sessions/analyses/reports) --------
    op.create_table(
        "history_index",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("player_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.Text, nullable=False),  # 'session' | 'analysis' | 'report'
        sa.Column("entity_ref", sa.Text, nullable=False),  # opaque id in the owning module
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        *_timestamps(),
    )
    op.create_index("ix_history_index_profile_time", "history_index", ["profile_id", "occurred_at"])

    # --- personal_baselines (per-metric distribution served to M15) --------
    op.create_table(
        "personal_baselines",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("player_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric_key", sa.Text, nullable=False),  # CIP-STD metric id
        sa.Column(
            "distribution",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),  # {count, mean, stddev, min, max, p25, p50, p75, ...}
        *_timestamps(),
    )
    op.create_index("ix_personal_baselines_profile", "personal_baselines", ["profile_id"])
    op.create_unique_constraint(
        "uq_personal_baselines_profile_metric",
        "personal_baselines",
        ["profile_id", "metric_key"],
    )

    # --- grants to the app role (no RLS: access control is the consent helper) -
    for table in PROFILE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO cip_app")


def downgrade() -> None:
    op.drop_table("personal_baselines")
    op.drop_table("history_index")
    op.drop_table("dna_snapshots")
    op.drop_table("dna_trait_history")
    op.drop_table("dna_traits")
    op.drop_table("player_profiles")
