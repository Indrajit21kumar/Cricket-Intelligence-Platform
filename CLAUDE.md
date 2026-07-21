# CLAUDE.md — Standing Instructions for Every CIP Session

This file is auto-loaded by Claude Code in every session inside this repository.
It is the operating contract for humans and AI agents contributing to CIP.
The rules below are BINDING and take precedence over general defaults.

---

## 1. Where the truth lives

The authoritative specification is the **CIP Blueprint** — a series of books
mirrored at `docs/specs/`:

- `Book 0 — Manifesto` — vision, principles, **Trust Doctrine** (measured / estimated / modelled)
- `Book 2 — Reference Architecture` — services, planes, pipeline, event contracts, multi-tenancy
- `Book 3 — Engineering Standards` — **BINDING** rules for coding, APIs, data, security, testing, CI/CD, and the Definition of Done
- `Book 4 — CIP-STD` — canonical analytical conventions (relevant once analytical modules are reached)
- Each module has its own spec: `docs/specs/CIP_M<xx>_*.md`

**Where the code and the spec disagree, the spec wins.** Update the code, not the spec.

## 2. Operating rules (non-negotiable)

- **Conform to Book 3 Engineering Standards by construction:**
  typed code, linting, standard error envelope, versioned APIs,
  `tenant_id` + row-level security on every tenant-scoped table,
  no secrets in code, structured logs/metrics/traces keyed by `correlation_id`.
- **A task is "done" ONLY when it meets the Book 3 Definition of Done** (Chapter 9, ten criteria).
- **Follow the current module's Claude Code Implementation Guide step by step, in order.**
- **Do NOT start a later module** until the current one's Acceptance Criteria all pass.
- **Every quantity that will later be stored MUST carry a provenance label**
  (measured / estimated / modelled) — enforce this at the schema level when relevant.
- **Ask the user before making an irreversible or costly decision**
  (cloud provider specifics, paid services). Otherwise choose a sensible,
  standards-compliant default and note it in your implementation notes.

## 3. Tech stack (from Book 3)

| Layer | Standard |
|-------|----------|
| Backend / services | Python 3.12 + FastAPI (async) |
| ML / vision | Python (PyTorch, OpenCV) |
| Web frontend | TypeScript + Next.js/React + Tailwind |
| Mobile | React Native (TypeScript) |
| Data | PostgreSQL, Redis, object storage, Kafka-compatible event bus |
| Container | Docker + orchestration (K8s or equivalent) |
| IaC | Terraform |

## 4. Locked M01 decisions

- **Package/workspace manager:** `uv` (workspace mode; members under `libs/` and `services/`)
- **Lint + format:** Ruff (both)
- **Type-check:** mypy strict
- **Test:** pytest + pytest-asyncio + pytest-cov + httpx
- **CI:** GitHub Actions (`.github/workflows/ci.yml`)
- **Contract tests:** Schemathesis against FastAPI's generated OpenAPI
- **Cloud target:** **DEFERRED.** Terraform folder is scaffolded but no provider is bound.
  Cloud (recommended GCP) is chosen at the M01→M02 handoff or later.
  `SecretProvider` currently ships with `env` / `file` implementations only.
- **Event bus:** Redpanda (Kafka wire) via `aiokafka` behind an `EventBus` interface
- **Observability:** OpenTelemetry SDK → OTLP; `structlog` bound to OTel
- **Idempotency store:** Redis via an `IdempotencyStore` interface

## 5. Repository layout

```
libs/                     shared foundation libraries
  cip-core/               config, tenancy, correlation, error envelope
  cip-observability/      structlog + OTel logs/metrics/traces
  cip-data/               SQLAlchemy async base, RLS helper, Alembic runner
  cip-events/             Kafka client, idempotency, DLQ
services/                 runnable services
  reference-service/      template new services copy from
migrations/base/          shared platform schema (tenants, tenant_members, audit_log)
infra/terraform/          IaC (provider-agnostic until a cloud is bound)
docker/                   local docker-compose (Postgres, Redpanda, Redis, OTel collector)
docs/                     documentation
  specs/                  markdown mirrors of the Books and module specs
  scaffolding.md          how to create a new CIP service
  standards-mapping.md    Book 3 chapter → where enforced in the repo
scripts/                  scaffolding + utility scripts
.github/workflows/ci.yml  Book 3 CI gate sequence
```

## 6. Common commands

```bash
uv sync --all-packages                     # install workspace + member deps + dev deps
uv run pre-commit install                  # enable local pre-commit hooks
uv run ruff check .                        # lint
uv run ruff format .                       # format
uv run mypy                                # type-check
uv run pytest -m "not integration and not contract"  # unit tests
uv run pytest -m integration               # integration (needs docker-compose up)
uv run pytest -m contract                  # contract (Schemathesis)
uv run bandit -r libs services -c pyproject.toml     # SAST
uv run pip-audit                           # dependency scan
docker compose -f docker/docker-compose.yml up -d    # local infra
```

## 7. Definition of Done (Book 3, Ch. 9)

A change is complete only when ALL applicable criteria pass:

1. Functional implementation meets the module's acceptance criteria
2. Unit tests (incl. formula fixtures) pass at required coverage
3. Integration + contract tests pass
4. AI validation passed against the golden dataset (model work only)
5. API/event contracts published and versioned
6. Security review + scans clean; provenance labels present (TRUST-001)
7. Performance within the stage's latency/throughput budget
8. Observability wired (logs, metrics, traces, alerts)
9. User + API documentation updated
10. Accessibility review for user-facing surfaces (WCAG 2.1 AA)

Criteria 4 and 10 do not apply to services that ship no model and no user-facing
surface — note their exclusion in the PR description.

## 8. What NOT to do

- Do not commit `.env`, secrets, credentials, API keys, or model weights.
- Do not use `git commit --no-verify` (bypasses pre-commit hooks).
- Do not `pip install` a package directly — always add to a `pyproject.toml` and `uv sync`.
- Do not write to `docs/specs/` — those files mirror the DOCX source of truth.
- Do not skip a module's Acceptance Criteria to move faster.
- Do not present an estimated value as if it were measured (TRUST-001 violation = defect).
