"""Secret loading — abstraction over the environment and (later) cloud secret managers.

Book 3 §2.2 forbids hard-coded secrets in source and §5.1 requires that
production secrets live in a managed store. ``SecretProvider`` is the seam
that lets us satisfy both today (env / file for local dev) and later
(AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault) without changing
any calling code — service code depends only on the protocol.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable


class SecretNotFoundError(KeyError):
    """Raised when a requested secret is not present in the configured backend."""


@runtime_checkable
class SecretProvider(Protocol):
    """Protocol every secret backend implements.

    Implementations MUST raise :class:`SecretNotFoundError` (not return a
    sentinel or ``None``) when a secret is absent. Absent-secret failures
    should be loud, not silent — Book 3 §2.2.
    """

    def get(self, name: str) -> str:
        """Return the value of the secret named ``name`` or raise."""
        ...


class EnvSecretProvider:
    """Read secrets from environment variables.

    Used in local dev where ``.env`` is loaded before the process starts.
    In production, prefer a cloud-native provider — env vars leak into logs
    and process listings.
    """

    def get(self, name: str) -> str:
        try:
            return os.environ[name]
        except KeyError as exc:
            raise SecretNotFoundError(name) from exc


class FileSecretProvider:
    """Read secrets from files under a base directory.

    Suitable for Kubernetes projected-volume secrets: each secret is a file
    whose name is the secret key and whose contents are the value. Trailing
    whitespace is stripped.
    """

    def __init__(self, base_dir: str | Path) -> None:
        self._base_dir = Path(base_dir)

    def get(self, name: str) -> str:
        path = self._base_dir / name
        try:
            return path.read_text(encoding="utf-8").rstrip("\n")
        except FileNotFoundError as exc:
            raise SecretNotFoundError(name) from exc


def build_provider(kind: str, **kwargs: object) -> SecretProvider:
    """Construct a provider by name — the string form used in configuration.

    Supported: ``"env"``, ``"file"`` (with ``base_dir=...``). Cloud backends
    (``"aws"``, ``"gcp"``, ``"vault"``) are added when a cloud is bound at
    M02+. An unknown kind raises :class:`ValueError`.
    """
    if kind == "env":
        return EnvSecretProvider()
    if kind == "file":
        base_dir = kwargs.get("base_dir")
        if not isinstance(base_dir, str | Path):
            raise ValueError("FileSecretProvider requires base_dir (str or Path)")
        return FileSecretProvider(base_dir)
    raise ValueError(f"Unknown secret provider kind: {kind!r}")
