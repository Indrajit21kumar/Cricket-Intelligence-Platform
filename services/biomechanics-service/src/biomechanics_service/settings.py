"""Service-specific settings — extends :class:`cip_core.Settings`."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from cip_core import Settings as CoreSettings


class ServiceSettings(CoreSettings):
    """Settings for the biomechanics-service."""

    model_config = SettingsConfigDict(
        env_prefix="CIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    service_name: str = Field("biomechanics-service")

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
    use_pose_only_source: bool = Field(
        False,
        description=(
            "Build strokes from M06's keypoint artefact alone, with no bat, "
            "ball or shot input. The bat/ball/shot detectors are stubs, so "
            "this is the only path whose numbers are genuinely measured."
        ),
    )
    local_storage_root: str = Field(
        default_factory=lambda: str(Path.home() / ".cip" / "local-storage"),
        description="Shared local object-storage root M06 writes its artefact to",
    )
    capture_fps: float = Field(
        30.0,
        description="Capture rate for the pose-only path; M06's artefact carries no metadata",
    )


@lru_cache(maxsize=1)
def get_service_settings() -> ServiceSettings:
    return ServiceSettings()
