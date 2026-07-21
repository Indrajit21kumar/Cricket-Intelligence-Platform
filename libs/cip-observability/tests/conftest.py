"""Shared fixtures for cip-observability tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cip_core import Settings, get_settings


@pytest.fixture
def settings() -> Iterator[Settings]:
    """Return a Settings instance with predictable service_name + env for tests."""
    get_settings.cache_clear()
    yield Settings(
        env="dev",
        service_name="test-service",
        log_level="DEBUG",
        secret_provider="env",
        _env_file=None,  # type: ignore[call-arg]
    )
    get_settings.cache_clear()
