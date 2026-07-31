# notification-service

M19 Notification — the platform's outbound messaging service. Listens for
events across the system (report ready, plan updated, billing/dunning,
sessions, identity) and delivers the right message to the right person on
the right channel (email, push, in-app), honouring preferences, quiet
hours, and consent (guardian-mediated for minors).

Run locally:

```bash
uv run uvicorn notification_service.main:app --reload
# then in another shell:
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
curl http://localhost:8000/internal/version
```
