# academy-service

M18 Academy / Coach Platform. The institutional composition layer: rosters
from M02 memberships, coach assignments, sessions and attendance, coach
dashboards composing M04/M14/M16/M17 outputs within access rules, team
analytics and fair leaderboards, and consented report sharing. Computes no
cricket analysis of its own — it composes and manages.

In Step 1 it exposes only the health endpoints so the CI gate sequence has a
real surface to test against.

Run locally:

```bash
uv run uvicorn academy_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
