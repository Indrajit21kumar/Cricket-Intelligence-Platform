# Book 3 Standards → Where Enforced

This table maps every binding standard from `docs/specs/CIP_Book3_Engineering_Standards_v1.0.md`
to the concrete place in this repository where it is enforced. If a row says
"planned in step N", the enforcement mechanism is scheduled for that M01 step.

## Chapter 2 — Coding Standards

| Standard | Enforcement |
|---|---|
| Python + FastAPI as primary stack | `pyproject.toml` `requires-python = ">=3.12"`; FastAPI listed as service dep |
| Static typing (mypy strict) | `[tool.mypy]` in root `pyproject.toml`; CI job `typecheck` |
| Lint + format (Ruff) | `[tool.ruff]` in root `pyproject.toml`; CI job `lint`; pre-commit hook |
| No hard-coded secrets | `SecretProvider` interface in `cip-core` (Step 2); `gitleaks` in pre-commit and CI |
| Explicit error handling | Standard error envelope in `cip-core.errors` (Step 2) |
| Trunk-based, PR-reviewed | GitHub branch protection (configured on the remote) |

## Chapter 3 — API Standards

| Standard | Enforcement |
|---|---|
| `/v1/` path versioning | Reference-service route prefix (Step 6) |
| Error envelope `{error:{code,message,details,request_id}}` | `cip-core.errors` (Step 2) |
| `Idempotency-Key` header on mutations | FastAPI dependency in `cip-core` (Step 2) |
| Cursor-based pagination | Helper in `cip-core.pagination` (added as needed by later modules) |
| OpenAPI contract + contract tests | Schemathesis CI job against FastAPI's `/openapi.json` |

## Chapter 4 — Data Standards

| Standard | Enforcement |
|---|---|
| UUID primary keys | `cip-data.base.Base` (Step 4) |
| `created_at` / `updated_at` on every table | `cip-data.base.TimestampMixin` (Step 4) |
| `tenant_id` + RLS on tenant-scoped tables | `cip-data.base.TenantScopedMixin` + `cip-data.rls` (Step 4) |
| Reversible Alembic migrations | `migrations/base/` (Step 4) |
| Metric provenance labels (TRUST-001) | Schema-level `provenance` enum on metric tables (introduced in M10+; skeleton in `cip-data` from Step 4) |

## Chapter 5 — Security & Privacy

| Standard | Enforcement |
|---|---|
| JWT/OAuth verification hook | Middleware slots in `cip-core` (Step 2); real verification in M02 |
| RBAC on every endpoint | Dependency in `cip-core.auth` (Step 2) |
| Secrets in managed store | `SecretProvider` interface (Step 2); real backends bound at M02+ |
| SAST | `bandit` CI job |
| Dependency scan | `pip-audit` CI job |
| Secrets scan | `gitleaks` CI job + pre-commit hook |
| Audit log for sensitive actions | `cip-core.audit.record()` (Step 7) writing to `audit_log` |

## Chapter 6 — Testing

| Standard | Enforcement |
|---|---|
| Unit tests with typical/boundary/degenerate fixtures | pytest suites under each package's `tests/` |
| Integration tests | pytest marker `-m integration` (needs docker-compose up) |
| Contract tests | Schemathesis CI job |
| Coverage on changed code | `pytest-cov`; threshold raised as libraries mature |

## Chapter 7 — DevOps

| Standard | Enforcement |
|---|---|
| Infrastructure as code | `infra/terraform/` (provider bound at M02+) |
| Isolated dev/staging/prod | Terraform `environments/` folder |
| CI: lint → type-check → unit → integration → contract → security → build | `.github/workflows/ci.yml` |
| Canary rollout + rollback | Wired at M02+ when a real cloud + K8s cluster exist |

## Chapter 8 — Observability

| Standard | Enforcement |
|---|---|
| Structured logs, metrics, traces keyed by `correlation_id` | `cip-observability` (Step 3) |
| SLOs per stage | Wired at M02+ (needs a real observability backend) |
| DLQ backlog alertable | Alerting wired at M02+; DLQ mechanism itself in `cip-events` (Step 5) |

## Chapter 9 — Definition of Done

Ten criteria; enforced per-PR via the checklist in `CLAUDE.md` §7.
The `.github/workflows/ci.yml` gate sequence covers the automatable subset.
