# migrations/base

Alembic migrations for the shared platform schema (`tenants`, `tenant_members`,
`audit_log`). Populated during **M01 Step 4**.

Each tenant-scoped table (in this and every downstream module) MUST have RLS
policies applied via the helper in `cip-data`.
