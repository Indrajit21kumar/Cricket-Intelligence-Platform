"""Service-specific settings — extends :class:`cip_core.Settings`."""

from __future__ import annotations

from functools import lru_cache

from cip_core import Settings as CoreSettings
from pydantic import Field
from pydantic_settings import SettingsConfigDict


class ServiceSettings(CoreSettings):
    """Settings for the reference-service."""

    model_config = SettingsConfigDict(
        env_prefix="CIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = Field("reference-service")

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


@lru_cache(maxsize=1)
def get_service_settings() -> ServiceSettings:
    return ServiceSettings()
