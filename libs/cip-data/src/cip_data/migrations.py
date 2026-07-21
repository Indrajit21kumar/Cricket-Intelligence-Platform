"""Programmatic Alembic runners.

Alembic normally runs via its CLI (``alembic upgrade head``). These wrappers
let tests and orchestration code drive migrations from Python without
shelling out — the same code path Book 3 §7 mandates for CD (migrations
gate every deploy).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config

# Repo layout: <repo>/migrations/base/  (populated in this same step).
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parents[4] / "migrations" / "base"


def _config(
    database_url: str,
    migrations_dir: Path | None = None,
) -> Config:
    """Build an Alembic ``Config`` pointing at a chosen directory + database."""
    directory = migrations_dir or DEFAULT_MIGRATIONS_DIR
    cfg = Config()
    cfg.set_main_option("script_location", str(directory))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_head(database_url: str, migrations_dir: Path | None = None) -> None:
    """Apply every migration up to head."""
    command.upgrade(_config(database_url, migrations_dir), "head")


def downgrade_base(database_url: str, migrations_dir: Path | None = None) -> None:
    """Roll every migration back to base."""
    command.downgrade(_config(database_url, migrations_dir), "base")


def current(database_url: str, migrations_dir: Path | None = None) -> None:
    """Print the current revision — thin wrapper around ``alembic current``."""
    command.current(_config(database_url, migrations_dir))
