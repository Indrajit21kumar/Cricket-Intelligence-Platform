"""M19 notification schema: notifications, preferences, delivery_attempts.

Revision ID: 0001_notification_schema
Revises:
Create Date: 2026-07-31

Creates notification-service's three tables per M19 §9. Depends on the M01
base migration only (no tenant FK — see below).

Person-anchored, not tenant-owned
----------------------------------
None of §9's three tables carry a ``tenant_id`` in their own column list — a
deliberate reading, not an omission: a person's notification inbox and
preferences span every tenant they belong to (a coach in two academies, a
parent with children at different academies), so there is no single tenant
context under which "list my notifications" makes sense. This mirrors M04's
``player_profiles``/M16's ``dna_update_runs`` (§9's own column lists there
are equally tenant_id-free) rather than M18's tenant-scoped tables. No RLS;
access control is app-layer (consent/ownership, same as M04/M16), all DB
access via ``admin_session``.

``idempotency_key`` (FR-M19-07, NFR-M19-02) is UNIQUE on its own — the
glossary names it as the already-encoded (event, recipient, channel) tuple,
not three separate columns to combine here.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_notification_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHANNELS = ("email", "push", "in_app")
STATUSES = ("pending", "sent", "delivered", "failed", "dead_lettered")


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recipient_ref", postgresql.UUID(as_uuid=True), nullable=False),
        # The notification type this event was mapped to (Step 2), e.g.
        # "report.ready" — its transactional/engagement category is a
        # property of the type, looked up in code, not stored per-row.
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        # The source event's correlation/idempotency reference (e.g. M14's
        # report correlation_id, M17's session_ref).
        sa.Column("event_ref", sa.Text, nullable=False),
        # (event, recipient, channel), pre-encoded by the caller — the
        # FR-M19-07 dedup anchor.
        sa.Column("idempotency_key", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(f"channel IN {CHANNELS!r}", name="ck_notifications_channel"),
        sa.CheckConstraint(f"status IN {STATUSES!r}", name="ck_notifications_status"),
    )
    op.create_index("ix_notifications_recipient", "notifications", ["recipient_ref"])
    op.create_unique_constraint(
        "uq_notifications_idempotency_key", "notifications", ["idempotency_key"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON notifications TO cip_app")

    op.create_table(
        "preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("person_ref", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        # The notification type/topic this preference governs.
        sa.Column("topic", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        # {"start_hour": int, "end_hour": int, "timezone": str} or NULL (none set).
        sa.Column("quiet_hours", postgresql.JSONB, nullable=True),
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
        sa.CheckConstraint(f"channel IN {CHANNELS!r}", name="ck_preferences_channel"),
    )
    op.create_index("ix_preferences_person", "preferences", ["person_ref"])
    op.create_unique_constraint(
        "uq_preferences_person_channel_topic", "preferences", ["person_ref", "channel", "topic"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON preferences TO cip_app")

    op.create_table(
        "delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        # The channel provider's own message/delivery id, if any.
        sa.Column("provider_ref", sa.Text, nullable=True),
        sa.Column(
            "at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("status IN ('success', 'failure')", name="ck_delivery_attempts_status"),
    )
    op.create_index("ix_delivery_attempts_notification", "delivery_attempts", ["notification_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON delivery_attempts TO cip_app")


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_table("preferences")
    op.drop_table("notifications")
