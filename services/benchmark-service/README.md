# benchmark-service

M15 Benchmark Intelligence. Compares a player's M10/M11 metrics against
skill-tier/age-band/legend-style benchmarks (Book 5 CIBL) and the player's own
history, explains every gap, and computes the guardrailed Legend Similarity
Score. Publishes `benchmark.compared` for M13/M14/M16.

In Step 1 it exposes only the health endpoints so the CI gate sequence has a
real surface to test against.

Run locally:

```bash
uv run uvicorn benchmark_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
