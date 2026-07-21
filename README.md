# Cricket Intelligence Platform (CIP)

> Democratise elite cricket coaching using explainable AI — every cricketer, from an
> eight-year-old in a local net to an international professional, receiving world-class
> biomechanical and tactical feedback from an ordinary smartphone.

This monorepo hosts every CIP service and shared library. The authoritative
specification is the **CIP Blueprint** — a series of books mirrored at
[`docs/specs/`](docs/specs/); the code follows the spec, not the other way around.

Start by reading [`CLAUDE.md`](CLAUDE.md) at the repo root — it is the operating
contract for humans and AI agents contributing to this codebase.

## Status

Currently building **Module M01 — Platform Foundation**, the shared skeleton
every other CIP service is built on. See
[`docs/specs/CIP_M01_Platform_Foundation_v1.0.md`](docs/specs/CIP_M01_Platform_Foundation_v1.0.md)
for the full module spec.

## Quick start

Requires Python 3.12 (managed by `uv`), Docker Desktop (for local infra, from Step 4).

```bash
# One-time
python -m pip install --user uv
uv sync --all-packages
uv run pre-commit install

# Run the reference service
uv run uvicorn reference_service.main:app --reload

# Run the local CI gate sequence
uv run ruff check .
uv run mypy
uv run pytest
```

## Repository layout

See [`CLAUDE.md`](CLAUDE.md) §5 for the full layout and the reasoning behind it.

## License

Proprietary — see [`LICENSE`](LICENSE).
