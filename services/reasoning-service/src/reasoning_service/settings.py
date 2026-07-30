"""Service-specific settings — extends :class:`cip_core.Settings`."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from cip_core import Settings as CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for the reasoning-service."""

    model_config = SettingsConfigDict(
        env_prefix="CIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = Field("reasoning-service")

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
