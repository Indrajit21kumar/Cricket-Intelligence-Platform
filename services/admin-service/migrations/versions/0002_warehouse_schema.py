"""M20 analytics warehouse: a separate Postgres schema, fed by events.

Revision ID: 0002_warehouse_schema
Revises: 0001_admin_ops_schema
Create Date: 2026-07-31

NFR-M20-03 requires the warehouse to never impact production database
performance. A genuinely separate columnar store (e.g. a dedicated
ClickHouse/BigQuery instance) is real infrastructure this build defers, same
as every other module has deferred infrastructure it doesn't yet have
(adapters + fakes, Book 3's stated approach) — but the LOGICAL separation is
real and enforced here: the warehouse lives in its own Postgres ``schema``
(``warehouse``), a disjoint namespace from every production service's
tables, written only by this service's ingestion worker and read only by
this service's analytics queries. No production service's schema, RLS
policy, or query plan is touched by anything in this migration.

Star schema (Book 1 Ch. 20; §9's "fact/dimension tables — analyses, usage,
revenue, model metrics"):

- ``fact_usage_event``   — one row per platform pipeline event (usage/adoption).
- ``fact_revenue_event`` — one row per M03 billing event (MRR/churn/conversion).
- ``dim_date``           — the shared date dimension both facts roll up against.

(``fact_model_metric`` — the model-oversight fact table — is added by Step
5's migration, once that step defines what it measures.)

Every fact row carries the producing event's ``idempotency_key`` as
``dedupe_key`` (unique), so a replayed event is a no-op re-ingest rather than
a duplicate row — the same dedup anchor :mod:`cip_events` itself uses.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_warehouse_schema"
down_revision: str | Sequence[str] | None = "0001_admin_ops_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"
WAREHOUSE_TABLES = ("fact_usage_event", "fact_revenue_event", "dim_date")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "fact_usage_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_topic", sa.Text, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("correlation_id", sa.Text, nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dedupe_key", sa.Text, nullable=False),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_fact_usage_event_dedupe", "fact_usage_event", ["dedupe_key"], schema=SCHEMA
    )
    op.create_index(
        "ix_fact_usage_event_topic_time",
        "fact_usage_event",
        ["event_topic", "occurred_at"],
        schema=SCHEMA,
    )
    op.create_index(
        "ix_fact_usage_event_tenant_time",
        "fact_usage_event",
        ["tenant_id", "occurred_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "fact_revenue_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_topic", sa.Text, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("dedupe_key", sa.Text, nullable=False),
        # Minor currency units (e.g. cents) — same convention billing-service
        # itself uses (``amount_minor``), so no unit conversion happens here.
        sa.Column("amount_minor", sa.BigInteger, nullable=True),
        sa.Column("currency", sa.Text, nullable=True),
        sa.Column(
            "payload", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        schema=SCHEMA,
    )
    op.create_unique_constraint(
        "uq_fact_revenue_event_dedupe", "fact_revenue_event", ["dedupe_key"], schema=SCHEMA
    )
    op.create_index(
        "ix_fact_revenue_event_topic_time",
        "fact_revenue_event",
        ["event_topic", "occurred_at"],
        schema=SCHEMA,
    )

    op.create_table(
        "dim_date",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=False),
        sa.Column("day", sa.Integer, nullable=False),
        sa.Column("iso_week", sa.Integer, nullable=False),
        sa.Column("iso_dow", sa.Integer, nullable=False),  # 1=Monday .. 7=Sunday
        schema=SCHEMA,
    )

    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO cip_app")
    for table in WAREHOUSE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO cip_app")


def downgrade() -> None:
    op.drop_table("dim_date", schema=SCHEMA)
    op.drop_table("fact_revenue_event", schema=SCHEMA)
    op.drop_table("fact_usage_event", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
