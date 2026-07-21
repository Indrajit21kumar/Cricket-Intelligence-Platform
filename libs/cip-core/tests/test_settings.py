"""Tests for :mod:`cip_core.settings`."""

from __future__ import annotations

from pathlib import Path

import pytest

from cip_core.secrets import EnvSecretProvider, FileSecretProvider
from cip_core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Force each test to re-parse the environment."""
    get_settings.cache_clear()


class TestDefaults:
    def test_defaults_are_sensible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure no lingering env vars from the outer shell contaminate defaults.
        for key in (
            "CIP_ENV",
            "CIP_SERVICE_NAME",
            "CIP_LOG_LEVEL",
            "CIP_SECRET_PROVIDER",
        ):
            monkeypatch.delenv(key, raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.env == "dev"
        assert s.service_name == "unknown-service"
        assert s.log_level == "INFO"
        assert s.secret_provider == "env"


class TestEnvOverrides:
    def test_env_vars_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "prod")
        monkeypatch.setenv("CIP_SERVICE_NAME", "identity-service")
        monkeypatch.setenv("CIP_LOG_LEVEL", "DEBUG")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert s.env == "prod"
        assert s.service_name == "identity-service"
        assert s.log_level == "DEBUG"

    def test_invalid_env_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_ENV", "not-a-real-env")
        with pytest.raises(ValueError):
            Settings(_env_file=None)  # type: ignore[call-arg]


class TestSecretProviderSelection:
    def test_env_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert isinstance(s.build_secret_provider(), EnvSecretProvider)

    def test_file_provider(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("CIP_SECRET_PROVIDER", "file")
        monkeypatch.setenv("CIP_SECRET_PROVIDER_DIR", str(tmp_path))
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        assert isinstance(s.build_secret_provider(), FileSecretProvider)

    def test_file_provider_without_dir_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_SECRET_PROVIDER", "file")
        monkeypatch.delenv("CIP_SECRET_PROVIDER_DIR", raising=False)
        s = Settings(_env_file=None)  # type: ignore[call-arg]
        with pytest.raises(ValueError, match="requires CIP_SECRET_PROVIDER_DIR"):
            s.build_secret_provider()


class TestGetSettingsCache:
    def test_returns_same_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CIP_SERVICE_NAME", "svc-1")
        first = get_settings()
        # Mutating env after first call should NOT change the cached value.
        monkeypatch.setenv("CIP_SERVICE_NAME", "svc-2")
        second = get_settings()
        assert first is second
        assert second.service_name == "svc-1"
