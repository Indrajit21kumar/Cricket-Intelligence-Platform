"""Runtime configuration shared by every CIP service.

Non-secret configuration comes from environment variables (loaded from
``.env`` in local dev). Secrets are pulled from a :class:`SecretProvider`
so we can swap backends without changing calling code (Book 3 §5.1).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cip_core.secrets import EnvSecretProvider, FileSecretProvider, SecretProvider

Environment = Literal["dev", "staging", "prod"]


class Settings(BaseSettings):
    """Base settings — services extend this with their own fields.

    All fields are typed and validated by pydantic. Environment variable
    names use the ``CIP_`` prefix so a service's config is grep-able and
    conflicts with third-party env vars are unlikely.
    """

    model_config = SettingsConfigDict(
        env_prefix="CIP_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Environment = Field("dev", description="Deployment environment")
    service_name: str = Field("unknown-service", description="Logical service name")
    log_level: str = Field("INFO", description="Root log level")

    secret_provider: Literal["env", "file"] = Field("env", description="Backend for secret lookups")
    secret_provider_dir: str | None = Field(
        None, description="Base dir for the 'file' secret provider (K8s secrets mount)"
    )

    def build_secret_provider(self) -> SecretProvider:
        """Instantiate the configured secret backend."""
        # nosec B105: "env" and "file" are backend identifiers, not passwords.
        if self.secret_provider == "env":  # nosec B105
            return EnvSecretProvider()
        if self.secret_provider == "file":  # nosec B105
            if not self.secret_provider_dir:
                raise ValueError("secret_provider='file' requires CIP_SECRET_PROVIDER_DIR")
            return FileSecretProvider(self.secret_provider_dir)
        raise ValueError(f"Unknown secret provider: {self.secret_provider!r}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    Cached so env parsing happens once. Call :func:`get_settings.cache_clear`
    in tests that need to reload from a mutated environment.
    """
    return Settings()
