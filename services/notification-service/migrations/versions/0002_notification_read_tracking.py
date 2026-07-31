"""M19 Step 6: track in-app read state on notifications.

Revision ID: 0002_notification_read_tracking
Revises: 0001_notification_schema
Create Date: 2026-07-31

§9's own column list for ``notifications`` (id, recipient_ref, type,
channel, status, event_ref, idempotency_key, created_at) has no column for
"has the recipient seen this in-app notification" — a different axis from
``status`` (whether the SEND succeeded, not whether it's been read).
§10's ``POST /v1/notifications/{id}/read`` needs somewhere to persist that,
so this step adds it additively, the same practice as M11's fps addition
to M10's contract and M16's retroactive ``evidence_value`` field.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_notification_read_tracking"
down_revision: str | Sequence[str] | None = "0001_notification_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("notifications", "read_at")
