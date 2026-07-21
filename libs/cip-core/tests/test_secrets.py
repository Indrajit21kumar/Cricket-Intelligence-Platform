"""Tests for :mod:`cip_core.secrets`."""

from __future__ import annotations

from pathlib import Path

import pytest
from cip_core.secrets import (
    EnvSecretProvider,
    FileSecretProvider,
    SecretNotFoundError,
    SecretProvider,
    build_provider,
)


class TestEnvSecretProvider:
    def test_returns_env_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_TEST_SECRET", "hunter2")
        assert EnvSecretProvider().get("CIP_TEST_SECRET") == "hunter2"

    def test_missing_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("CIP_DEFINITELY_NOT_SET", raising=False)
        with pytest.raises(SecretNotFoundError):
            EnvSecretProvider().get("CIP_DEFINITELY_NOT_SET")


class TestFileSecretProvider:
    def test_returns_file_contents(self, tmp_path: Path) -> None:
        (tmp_path / "db-password").write_text("s3cr3t\n", encoding="utf-8")
        assert FileSecretProvider(tmp_path).get("db-password") == "s3cr3t"

    def test_strips_only_trailing_newlines(self, tmp_path: Path) -> None:
        (tmp_path / "token").write_text("abc\n\n", encoding="utf-8")
        assert FileSecretProvider(tmp_path).get("token") == "abc"

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SecretNotFoundError):
            FileSecretProvider(tmp_path).get("does-not-exist")

    def test_accepts_string_path(self, tmp_path: Path) -> None:
        (tmp_path / "k").write_text("v")
        assert FileSecretProvider(str(tmp_path)).get("k") == "v"


class TestBuildProvider:
    def test_env_kind(self) -> None:
        provider = build_provider("env")
        assert isinstance(provider, EnvSecretProvider)
        assert isinstance(provider, SecretProvider)

    def test_file_kind(self, tmp_path: Path) -> None:
        provider = build_provider("file", base_dir=str(tmp_path))
        assert isinstance(provider, FileSecretProvider)

    def test_file_kind_without_base_dir(self) -> None:
        with pytest.raises(ValueError, match="requires base_dir"):
            build_provider("file")

    def test_unknown_kind(self) -> None:
        with pytest.raises(ValueError, match="Unknown secret provider"):
            build_provider("magical-cloud")
