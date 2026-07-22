# billing-service (M03)

Subscription & Billing — the commercial engine. Owns plans, entitlements,
metered usage, subscription lifecycle, invoices (reconciled from an external
payment provider via a swappable adapter), dunning, and seats. Built on
M01 primitives + M02 identity.

**CIP never moves money.** The external payment provider does. This service
records intent + reconciles provider webhooks, and never stores raw card
data (NFR-M03-03). In dev/test a fake provider simulates the provider.

Spec: [`docs/specs/CIP_M03_Subscription_Billing_v1.0.md`](../../docs/specs/CIP_M03_Subscription_Billing_v1.0.md).

## Own migrations

```bash
uv run python -c "from cip_data.migrations import upgrade_head; from pathlib import Path; \
    upgrade_head('postgresql+asyncpg://cip:cip@localhost:5432/cip', \
    migrations_dir=Path('services/billing-service/migrations'))"
```

## Run locally

```bash
docker compose -f docker/docker-compose.yml up -d
uv run uvicorn billing_service.main:app --env-file .env --reload
```
