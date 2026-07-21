.PHONY: help install lint format typecheck test unit integration contract security ci infra-up infra-down clean

help:
	@echo "CIP developer commands (see CLAUDE.md §6 for the full list)"
	@echo ""
	@echo "  make install       Install workspace + dev deps"
	@echo "  make lint          Run Ruff lint + format check"
	@echo "  make format        Auto-format with Ruff"
	@echo "  make typecheck     Run mypy strict"
	@echo "  make unit          Run unit tests"
	@echo "  make integration   Run integration tests (requires infra-up)"
	@echo "  make contract      Run contract tests"
	@echo "  make security      Run bandit + pip-audit"
	@echo "  make ci            Run the full local CI gate sequence"
	@echo "  make infra-up      docker compose up local Postgres/Redpanda/Redis/OTel"
	@echo "  make infra-down    docker compose down"
	@echo "  make clean         Remove caches and build artefacts"

install:
	uv sync --all-packages
	uv run pre-commit install

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

typecheck:
	uv run mypy

unit:
	uv run pytest -m "not integration and not contract"

integration:
	uv run pytest -m integration

contract:
	uv run pytest -m contract

security:
	uv run bandit -r libs services -c pyproject.toml
	uv export --no-emit-workspace --no-editable --no-hashes --format requirements-txt --quiet > requirements-audit.txt
	uv run pip-audit --strict -r requirements-audit.txt
	rm -f requirements-audit.txt

ci: lint typecheck unit security
	@echo "Local CI gates passed."

infra-up:
	docker compose -f docker/docker-compose.yml up -d

infra-down:
	docker compose -f docker/docker-compose.yml down

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name '*.egg-info' -exec rm -rf {} +
