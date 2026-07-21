"""Unit tests for :mod:`scripts.scaffold_service`.

These tests operate on a temporary copy of the repo to avoid touching the
real ``services/`` tree.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCAFFOLD_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scaffold_service.py"
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def scaffold_module(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:
    """Import scaffold_service against a temp repo so it doesn't mutate ours."""
    # Copy the real reference-service into the temp repo so the script has
    # something to copy from.
    (tmp_path / "services").mkdir()
    shutil.copytree(
        REPO_ROOT / "services" / "reference-service",
        tmp_path / "services" / "reference-service",
    )
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCAFFOLD_SCRIPT, tmp_path / "scripts" / "scaffold_service.py")

    # Import under an isolated name so tests are hermetic.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_test_scaffold_service", tmp_path / "scripts" / "scaffold_service.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["_test_scaffold_service"] = module
    spec.loader.exec_module(module)

    # Point REPO_ROOT-derived constants at the temp copy.
    module.REPO_ROOT = tmp_path
    module.SOURCE_SERVICE = tmp_path / "services" / "reference-service"
    return module


class TestScaffold:
    def test_creates_new_service_dir(self, scaffold_module: object) -> None:
        result = scaffold_module.scaffold("identity-service")
        assert result.exists()
        assert result.name == "identity-service"

    def test_renames_python_package(self, scaffold_module: object) -> None:
        result = scaffold_module.scaffold("identity-service")
        assert (result / "src" / "identity_service").is_dir()
        assert not (result / "src" / "reference_service").exists()

    def test_updates_pyproject_name(self, scaffold_module: object) -> None:
        result = scaffold_module.scaffold("identity-service")
        pyproject = (result / "pyproject.toml").read_text(encoding="utf-8")
        assert 'name = "identity-service"' in pyproject
        assert 'name = "reference-service"' not in pyproject

    def test_updates_source_imports(self, scaffold_module: object) -> None:
        result = scaffold_module.scaffold("identity-service")
        main_py = (result / "src" / "identity_service" / "main.py").read_text(encoding="utf-8")
        assert "identity_service" in main_py
        assert "reference_service" not in main_py

    def test_refuses_existing_target(self, scaffold_module: object) -> None:
        scaffold_module.scaffold("identity-service")
        with pytest.raises(SystemExit, match="already exists"):
            scaffold_module.scaffold("identity-service")

    def test_refuses_source_name(self, scaffold_module: object) -> None:
        with pytest.raises(SystemExit, match="cannot scaffold"):
            scaffold_module.scaffold("reference-service")

    def test_refuses_empty_name(self, scaffold_module: object) -> None:
        with pytest.raises(SystemExit, match="empty"):
            scaffold_module.scaffold("")

    def test_refuses_bad_chars(self, scaffold_module: object) -> None:
        with pytest.raises(SystemExit, match="alphanumeric"):
            scaffold_module.scaffold("bad name!")

    def test_refuses_leading_hyphen(self, scaffold_module: object) -> None:
        with pytest.raises(SystemExit, match="start or end"):
            scaffold_module.scaffold("-oops")
