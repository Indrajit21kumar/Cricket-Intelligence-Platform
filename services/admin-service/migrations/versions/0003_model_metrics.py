"""M20 model-oversight fact table: warehouse.fact_model_metric.

Revision ID: 0003_model_metrics
Revises: 0002_warehouse_schema
Create Date: 2026-07-31

Deferred from Step 1's migration deliberately (see that migration's own
docstring) until Step 5 defined what this table actually measures:
per-model accuracy-vs-golden, confidence calibration, over time
(FR-M20-05). No production service publishes this telemetry as an event
today — the golden-dataset gates M06-M09 Step 7/8 built are CI-time
validation, not a runtime stream — so unlike ``fact_usage_event``/
``fact_revenue_event`` this table has no ingestion worker feeding it yet.
:func:`admin_service.domain.model_metrics_repo.record_model_metric` is the
real, tested write path a future telemetry consumer will call.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_model_metrics"
down_revision: str | Sequence[str] | None = "0002_warehouse_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "warehouse"


def upgrade() -> None:
    op.create_table(
        "fact_model_metric",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_name", sa.Text, nullable=False),
        sa.Column("model_version", sa.Text, nullable=False),
        sa.Column("metric_name", sa.Text, nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_fact_model_metric_lookup",
        "fact_model_metric",
        ["model_name", "metric_name", "computed_at"],
        schema=SCHEMA,
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.fact_model_metric TO cip_app")


def downgrade() -> None:
    op.drop_table("fact_model_metric", schema=SCHEMA)
