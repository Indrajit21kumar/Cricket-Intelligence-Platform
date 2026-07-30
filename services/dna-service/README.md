# dna-service

M16 Cricket DNA. Computes a player's evolving technical trait profile from
each session's M10/M11 metrics, M13 findings, and M15 benchmark position, via
a confidence-weighted decay/EMA update, and writes versioned updates through
M04's write path — the only writer of trait values. Publishes `dna.updated`.

In Step 1 it exposes only the health endpoints so the CI gate sequence has a
real surface to test against.

Run locally:

```bash
uv run uvicorn dna_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
