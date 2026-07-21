"""Unit tests for :mod:`cip_data.engine`."""

from __future__ import annotations

import pytest

from cip_data.engine import build_engine


class TestBuildEngine:
    def test_rejects_sync_url(self) -> None:
        with pytest.raises(ValueError, match="asyncpg"):
            build_engine("postgresql://user:pw@localhost:5432/db")

    def test_rejects_sqlite_url(self) -> None:
        with pytest.raises(ValueError, match="asyncpg"):
            build_engine("sqlite:///./test.db")

    def test_accepts_asyncpg_url(self) -> None:
        engine = build_engine("postgresql+asyncpg://user:pw@localhost:5432/db")
        assert engine is not None
