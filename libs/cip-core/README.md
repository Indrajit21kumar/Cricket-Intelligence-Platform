# cip-core

Shared foundation library — consumed by every CIP service.

**Contents (built during M01 Step 2 and later):**

- Configuration loading (env + `SecretProvider` interface)
- Tenancy context (`TenantContext` via `contextvars`)
- Correlation-id context and header propagation
- Standard error envelope `{error:{code,message,details,request_id}}`
- Error taxonomy shared across services
- FastAPI middleware to extract tenant/correlation on every request
- `cip_core.audit.record()` audit-logging helper (Step 7)
