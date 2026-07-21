"""Scaffold a new CIP service from ``services/reference-service/``.

Usage
-----

.. code-block:: bash

    python scripts/scaffold_service.py identity-service

Creates ``services/identity-service/`` with the reference-service tree
copied over and package/module names renamed (``reference_service`` ->
``identity_service``). Then run ``uv sync --all-packages`` to install the
new workspace member.

Design notes
------------

- **No template engine.** The script rewrites a fixed list of file paths
  and substitutes a fixed list of tokens. Anything more complex is
  service-specific and belongs in the new service itself, not here.
- **Idempotent-ish:** refuses to run if the target directory already
  exists (rename won't be safe otherwise). Fail-loud rather than
  overwrite silently.
- **Assumes hyphenated new-name.** ``foo-bar`` becomes the pyproject
  ``name = "foo-bar"`` and the Python package ``foo_bar``.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_SERVICE = REPO_ROOT / "services" / "reference-service"
SOURCE_PACKAGE = "reference_service"
SOURCE_NAME = "reference-service"


def scaffold(new_name: str) -> Path:
    """Copy the reference-service into a new services/<new_name>/ directory.

    Returns the path of the created service directory. Raises SystemExit
    on invalid input or if the target already exists.
    """
    _validate_name(new_name)
    new_pkg = new_name.replace("-", "_")

    target = REPO_ROOT / "services" / new_name
    if target.exists():
        raise SystemExit(
            f"error: {target} already exists; refusing to overwrite. "
            "Remove it first or pick a different name."
        )

    shutil.copytree(SOURCE_SERVICE, target)

    # Rename the src/<package>/ directory.
    src_pkg_dir = target / "src" / SOURCE_PACKAGE
    new_pkg_dir = target / "src" / new_pkg
    src_pkg_dir.rename(new_pkg_dir)

    # Rewrite every occurrence of the source names in every text file
    # inside the new service.
    _substitute_tree(target, new_name=new_name, new_pkg=new_pkg)

    return target


def _validate_name(name: str) -> None:
    if not name:
        raise SystemExit("error: service name must not be empty")
    if not name.replace("-", "").isalnum():
        raise SystemExit(f"error: service name {name!r} must be alphanumeric with hyphens")
    if name.startswith("-") or name.endswith("-"):
        raise SystemExit("error: service name must not start or end with '-'")
    if name == SOURCE_NAME:
        raise SystemExit(
            f"error: cannot scaffold a service called {SOURCE_NAME!r} "
            "(that name is taken by the template)"
        )


TEXT_SUFFIXES = frozenset({".py", ".toml", ".md", ".yml", ".yaml", ".ini", ".cfg", ""})


def _substitute_tree(root: Path, *, new_name: str, new_pkg: str) -> None:
    """Replace SOURCE_PACKAGE + SOURCE_NAME in every text file under ``root``."""
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        replaced = text.replace(SOURCE_PACKAGE, new_pkg).replace(SOURCE_NAME, new_name)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "name",
        help="Service name (kebab-case, e.g. 'identity-service')",
    )
    args = parser.parse_args(argv)
    target = scaffold(args.name)
    print(f"Scaffolded {target}")
    print("Next steps:")
    print("  uv sync --all-packages")
    print(f"  uv run pytest services/{args.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
