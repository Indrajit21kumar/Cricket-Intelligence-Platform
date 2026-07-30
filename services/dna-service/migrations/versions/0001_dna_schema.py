"""M16 DNA update-run log: dna_update_runs.

Revision ID: 0001_dna_schema
Revises:
Create Date: 2026-07-30

Creates dna-service's only table per M16 §9. Depends on the M01 base
migration only (no tenant FK — see below).

Person-anchored, not tenant-owned
----------------------------------
M16 owns NO trait storage — that is M04's job (the store/engine split, §8).
This table is only M16's own processing log: an audit/replay trail of the
updates M16 computed and wrote through M04. It carries no tenant_id and gets
no row-level security, mirroring M04's player_profiles exactly (§9's own
column list: ``id, player_id, session_ref, traits_updated, model_version,
computed_at`` — no tenant_id) — Cricket DNA is portable across academies
(ENG-002), so the engine that maintains it is scoped to the player, not a
tenant. Access control is app-layer (consent, same as M04), not RLS; all DB
access is via ``admin_session``.

``UNIQUE(player_id, session_ref)`` is the idempotency anchor (NFR-M16-03): a
re-delivered session's update is a no-op re-read of this row, never a
duplicate trait write.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_dna_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dna_update_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("player_id", postgresql.UUID(as_uuid=True), nullable=False),
        # The report/session this update was computed from (idempotency key).
        sa.Column("session_ref", sa.Text, nullable=False),
        # {trait_key: {prior_value, new_value, confidence, evidence_confidence}}.
        sa.Column(
            "traits_updated",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_dna_update_runs_player", "dna_update_runs", ["player_id"])
    op.create_unique_constraint(
        "uq_dna_update_runs_session", "dna_update_runs", ["player_id", "session_ref"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON dna_update_runs TO cip_app")


def downgrade() -> None:
    op.drop_table("dna_update_runs")
