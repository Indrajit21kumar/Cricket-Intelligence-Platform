# Creating a new CIP service

A new CIP service is created by copying [`services/reference-service/`](../services/reference-service)
via [`scripts/scaffold_service.py`](../scripts/scaffold_service.py). The
template inherits every Book 3 requirement (typed code, error envelope,
tenancy middleware, structured logs bound to `correlation_id`, DB with RLS,
Kafka-wire event bus, health probes, Dockerfile), so a scaffolded service
passes every CI gate on day one with no manual edits — that's
**AC-M01-01**.

## Step 1 — pick a kebab-case name

Names are `foo-bar` in every file (pyproject `name`, service directory,
Docker image) and `foo_bar` in Python (module path). Pick something clear:

- ✅ `identity-service`, `billing-service`, `video-intelligence`
- ❌ `IdentityService`, `identity_service`, `foo bar`, `123-service`

## Step 2 — run the scaffold script

From the repo root:

```bash
python scripts/scaffold_service.py identity-service
```

The script copies the reference-service tree, renames the Python package
(`reference_service` → `identity_service`), and rewrites every file
containing the source names. It refuses to overwrite an existing
directory — remove or rename first if you're re-scaffolding.

Confirm the new tree:

```
services/identity-service/
├── pyproject.toml          # name = "identity-service"
├── README.md
├── Dockerfile
├── .dockerignore
├── src/identity_service/
│   ├── __init__.py
│   ├── main.py             # create_app() factory
│   ├── settings.py         # extends cip_core.Settings
│   ├── deps.py             # DB / bus / Redis singletons
│   ├── health.py           # /health/live, /health/ready, /internal/version
│   └── routes.py           # POST /v1/demo/echo (delete + replace)
└── tests/
    ├── conftest.py
    ├── test_health.py
    ├── test_health_integration.py
    └── test_correlation_flow_integration.py
```

## Step 3 — install the new workspace member

```bash
uv sync --all-packages
```

`uv` picks up `services/identity-service/pyproject.toml` from the workspace
glob in the root `pyproject.toml` and installs the new package alongside the
existing ones.

## Step 4 — verify the scaffold is green out of the box

```bash
uv run ruff check .
uv run mypy
uv run pytest services/identity-service
```

Everything must pass with **no manual changes**. If it doesn't, the
template is broken — file a bug on M01 rather than editing around it.

## Step 5 — replace the demo endpoint with your service's own

The scaffolded service ships a `POST /v1/demo/echo` route so its
integration tests have something to exercise. Replace it with your
service's real endpoints:

1. Delete or rewrite `src/<pkg>/routes.py`.
2. Add new routers under `src/<pkg>/`.
3. Include them in `main.py`'s `create_app()`.
4. Update the integration tests in `tests/` to cover your real endpoints.

Keep the health + version endpoints — every service exposes them.

## Step 6 — add domain-specific dependencies

Edit `services/<name>/pyproject.toml`'s `dependencies` list and re-run
`uv sync --all-packages`. Book 3 mandates:

- Any DB tables use the mixins from `cip_data.base` + the RLS helpers
  from `cip_data.rls` in the service's own Alembic migrations.
- Any events use the `EventEnvelope` from `cip_events`; every consumer is
  wrapped in `IdempotentConsumer`.
- Any sensitive action calls `cip_core.audit.record(session, action=...,
  entity=..., actor=..., meta=...)` from within a `tenant_session`.
- Any secrets come from `Settings.build_secret_provider()`, never hard-coded.

## What you inherit for free

Because the template already wires:

- `cip_core.install(app)` — tenancy + correlation middleware, error envelope,
  exception handlers
- `cip_observability.configure_all(settings, app=app)` — structured logs +
  OTel traces + metrics + auto-instrumentation
- Lifespan-managed engine / bus / Redis singletons in `deps.py`
- `/health/live` and `/health/ready` with real dep probes
- `/internal/version`
- Dockerfile with multi-stage build + healthcheck

...you satisfy Book 3 §2, §3, §4, §5, §7, §8 by construction. Your service
code focuses purely on domain logic.

## Definition of Done for a new service

A scaffolded service is release-ready when its own PR clears every
[Book 3 Ch. 9](specs/CIP_Book3_Engineering_Standards_v1.0.md) criterion
that applies to its work type (typically 1-9; criterion 10 only if it has
user-facing surfaces).
