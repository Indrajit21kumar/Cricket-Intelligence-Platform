# admin-service

M20 Admin & Platform Analytics — the internal operator's console and the
platform's analytics warehouse. Restricted to `platform_admin`: user/tenant
administration, content moderation, revenue and usage reporting, per-model
oversight, and the biomechanics review-queue workflow. Every privileged
action is audited; cross-tenant access is inherent to this service and is
always logged.

Run locally:

```bash
uv run uvicorn admin_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```

Run the warehouse ingestion worker (consumes platform events into the
`warehouse` schema; a separate process from the API, same as every other
CIP worker):

```bash
uv run python -m admin_service.worker
```
