"""Service-specific settings — extends :class:`cip_core.Settings`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from cip_core import Settings as CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for the video-service."""

    model_config = SettingsConfigDict(
        env_prefix="CIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = Field("video-service")

    database_url: str = Field(
        "postgresql+asyncpg://cip:cip@localhost:5432/cip",
        description="asyncpg-scheme URL for the platform Postgres",
    )
    kafka_bootstrap: str = Field(
        "localhost:9092",
        description="Kafka-wire bootstrap servers (Redpanda in dev)",
    )
    redis_url: str = Field(
        "redis://localhost:6379/0",
        description="Redis URL for the idempotency store",
    )

    use_real_pipeline: bool = Field(
        False,
        description=(
            "Use local-filesystem storage + the OpenCV processor instead of the "
            "fakes. Requires the 'real' extra installed."
        ),
    )
    local_storage_root: str = Field(
        default_factory=lambda: str(Path.home() / ".cip" / "local-storage"),
        description="Shared local object-storage root (pose-service reads the same path)",
    )
    public_base_url: str = Field(
        "http://127.0.0.1:8003",
        description=(
            "Base URL clients reach this service on — used to mint upload URLs. "
            "8003 matches the port the web console's Vite proxy expects."
        ),
    )


@lru_cache(maxsize=1)
def get_service_settings() -> ServiceSettings:
    return ServiceSettings()
