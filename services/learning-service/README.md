# learning-service

M17 Learning Engine. Infers a player's learning stage from M16 DNA + M04
history, prioritises current M13 findings by impact x fixability x
stage-readiness, selects grounded drills with measurable objectives, tunes
dose/timeline to learning speed, and evaluates whether prior plan targets
were met. Publishes `plan.updated` for M14 to render and M18 to schedule.

In Step 1 it exposes only the health endpoints so the CI gate sequence has a
real surface to test against.

Run locally:

```bash
uv run uvicorn learning_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
