# reference-service

The runnable service template every new CIP service copies from.
As M01 progresses the template gains real middleware, DB wiring, and event
publishing/consumption; in Step 1 it exposes only the health endpoints so the
CI gate sequence has a real surface to test against.

Run locally:

```bash
uv run uvicorn reference_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
