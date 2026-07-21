"""SQLAlchemy 2.0 declarative base + mixins for the CIP schema.

Book 3 §4.1 mandates:

- UUID primary keys everywhere
- ``created_at`` and ``updated_at`` on every table
- ``tenant_id`` on every tenant-scoped table, with row-level security

The mixins in this module make those requirements zero-effort for the code
that consumes them: subclass ``TenantScopedBase`` and the columns and RLS
enforcement come for free.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    """Timezone-aware UTC now — used as SQLAlchemy default."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Root declarative base for every CIP model."""


class TimestampMixin:
    """``created_at`` + ``updated_at`` with server-side defaults.

    ``updated_at`` uses ``onupdate`` so ORM updates keep it fresh without the
    caller having to remember.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class UUIDPKMixin:
    """UUID primary key (Book 3 §4.1)."""

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TenantScopedMixin(UUIDPKMixin, TimestampMixin):
    """Combined mixin for tenant-scoped tables.

    Adds ``id`` (UUID PK), ``tenant_id`` (UUID FK to ``tenants``),
    ``created_at``, and ``updated_at``. Every tenant-scoped table MUST use
    this mixin AND the RLS helpers from :mod:`cip_data.rls` in its migration.
    """

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
