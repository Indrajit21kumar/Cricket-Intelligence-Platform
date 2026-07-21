# cip-data

Async SQLAlchemy 2.0 base, tenant row-level-security helper, and Alembic
migration runner. Built during M01 Step 4.

Every tenant-scoped table across the platform MUST include `tenant_id` and
`created_at`/`updated_at` (Book 3, Ch. 4) and MUST be governed by the RLS helper
provided here.
