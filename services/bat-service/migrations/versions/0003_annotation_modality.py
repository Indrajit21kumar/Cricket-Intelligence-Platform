"""Share the annotation queue between M07 (bat) and M08 (ball): add modality.

Revision ID: 0003_annotation_modality
Revises: 0002_annotation_queue
Create Date: 2026-07-24

Both M07 §9 and M08 §9 name ``annotation_queue`` — it is one platform-wide
flywheel, not one queue per vision module. M07 created it, so M07's Alembic
project keeps owning the DDL; ball-service uses the same tables through the
shared ``cip-annotation`` library rather than growing a parallel copy (which
would also mean a parallel copy of the consent gate).

``modality`` is the split. The uniqueness key gains it because a bat frame and
a ball frame from the same clip and frame index are DIFFERENT training items —
a labeller marking the bat is not marking the ball — so one clip may
legitimately appear once per modality. Without this the ON CONFLICT clause
would silently drop M08's frames whenever M07 had already queued that frame.

Existing rows are backfilled to 'bat', which is what they are: everything in
the queue before this migration came from M07.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_annotation_modality"
down_revision: str | Sequence[str] | None = "0002_annotation_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "annotation_queue",
        # Server default so the backfill is atomic with the add; the column is
        # NOT NULL from the start rather than nullable-then-tightened.
        sa.Column(
            "modality",
            sa.Text,
            nullable=False,
            server_default=sa.text("'bat'"),
        ),
    )
    op.create_index("ix_annotation_queue_modality", "annotation_queue", ["modality"])

    # Widen uniqueness to include modality.
    op.drop_constraint("uq_annotation_queue_frame", "annotation_queue", type_="unique")
    op.create_unique_constraint(
        "uq_annotation_queue_frame",
        "annotation_queue",
        ["tenant_id", "correlation_id", "modality", "frame_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_annotation_queue_frame", "annotation_queue", type_="unique")
    # Ball rows would collide with bat rows on the narrower key, so they cannot
    # survive the downgrade. Drop them explicitly rather than letting the
    # constraint fail with an opaque error.
    op.execute("DELETE FROM annotation_queue WHERE modality <> 'bat'")
    op.create_unique_constraint(
        "uq_annotation_queue_frame",
        "annotation_queue",
        ["tenant_id", "correlation_id", "frame_index"],
    )
    op.drop_index("ix_annotation_queue_modality", table_name="annotation_queue")
    op.drop_column("annotation_queue", "modality")
