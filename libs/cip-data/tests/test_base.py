"""Unit tests for :mod:`cip_data.base`.

Verifies the mixins produce the columns Book 3 §4.1 mandates without needing
a running database. Behavioural verification (RLS, migration apply/rollback)
lives in the integration suite.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Mapped, mapped_column

from cip_data.base import Base, TenantScopedMixin, TimestampMixin, UUIDPKMixin


class _Widget(TenantScopedMixin, Base):
    __tablename__ = "widgets_test"
    label: Mapped[str] = mapped_column()


class _Simple(TimestampMixin, UUIDPKMixin, Base):
    __tablename__ = "simple_test"


class TestTenantScopedMixin:
    def test_adds_uuid_pk(self) -> None:
        assert "id" in _Widget.__table__.columns
        assert _Widget.__table__.columns["id"].primary_key

    def test_adds_tenant_id(self) -> None:
        col = _Widget.__table__.columns["tenant_id"]
        assert col is not None
        assert not col.nullable
        # Has an index for tenant lookups.
        assert any("tenant_id" in idx.columns for idx in _Widget.__table__.indexes)

    def test_adds_timestamps(self) -> None:
        assert "created_at" in _Widget.__table__.columns
        assert "updated_at" in _Widget.__table__.columns
        assert not _Widget.__table__.columns["created_at"].nullable
        assert not _Widget.__table__.columns["updated_at"].nullable

    def test_tenant_id_is_uuid_typed(self) -> None:
        # Python-side annotation must be uuid.UUID for type safety.
        col = _Widget.__table__.columns["tenant_id"]
        # Column .type carries the SQLAlchemy type; python_type must be uuid.UUID.
        assert col.type.python_type is uuid.UUID


class TestTimestampMixin:
    def test_default_is_set(self) -> None:
        assert _Simple.__table__.columns["created_at"].default is not None

    def test_utcnow_returns_utc_datetime(self) -> None:
        # Verify the helper function directly — SQLAlchemy wraps the callable
        # in a context-taking form when it stores it on the column default.
        from cip_data.base import _utcnow

        value = _utcnow()
        assert isinstance(value, datetime)
        assert value.tzinfo is not None

    def test_updated_at_has_onupdate(self) -> None:
        assert _Simple.__table__.columns["updated_at"].onupdate is not None
