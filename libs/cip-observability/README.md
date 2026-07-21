# cip-observability

Structured logs, metrics, and distributed traces — all keyed by `correlation_id`.
Built during M01 Step 3.

Backends are backend-agnostic (OTLP); the local dev collector runs via
`docker/docker-compose.yml`; production endpoints are configured per environment.
