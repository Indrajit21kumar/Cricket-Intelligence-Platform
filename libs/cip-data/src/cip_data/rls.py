"""Row-level security SQL helpers, used from Alembic migrations.

Every tenant-scoped table MUST have RLS enabled with the standard
``tenant_isolation`` policy — the fixed contract:

.. code-block:: sql

    USING     (tenant_id = current_setting('cip.tenant_id')::uuid)
    WITH CHECK (tenant_id = current_setting('cip.tenant_id')::uuid)

``USING`` blocks reads / updates of other tenants' rows; ``WITH CHECK``
blocks INSERT/UPDATE that would place a row under a different tenant. The
GUC ``cip.tenant_id`` is set by :func:`cip_data.engine.tenant_session` via
``SET LOCAL`` on the transaction, so the setting is scoped and cannot leak
between sessions.

Migrations call :func:`enable_rls_sql` and :func:`tenant_isolation_policy_sql`
to emit the exact statements. Keeping the SQL in one place stops each
table's migration from re-deriving the shape (and getting it subtly wrong).
"""

from __future__ import annotations

TENANT_GUC = "cip.tenant_id"


def enable_rls_statements(table: str) -> list[str]:
    """Return SQL statements enabling RLS on ``table`` and forcing it.

    Returned as a list because asyncpg's prepared-statement protocol rejects
    multiple statements in a single call. Callers execute each statement
    separately (via ``op.execute`` in Alembic, or ``session.execute`` in tests).

    ``FORCE ROW LEVEL SECURITY`` is critical: without it, the table owner
    (which is the connecting role in dev) bypasses RLS silently and negative
    tests would pass while real prod would still be broken.
    """
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY",
    ]


def tenant_isolation_policy_sql(table: str, *, policy_name: str = "tenant_isolation") -> str:
    """Return the CREATE POLICY statement for the ``tenant_isolation`` policy.

    Reads: only rows whose ``tenant_id`` matches the session GUC are visible.
    Writes: INSERT/UPDATE must place the row under the session's tenant.

    ``NULLIF(current_setting(...), '')`` handles the "not set" case: Postgres'
    ``current_setting(name, true)`` returns the empty string (not NULL) when
    the GUC was never set, and ``''::uuid`` would raise. Coalescing to NULL
    means the ``tenant_id = NULL`` comparison is UNKNOWN → rows filtered.
    """
    return (
        f"CREATE POLICY {policy_name} ON {table}\n"
        f"    USING (tenant_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)\n"
        f"    WITH CHECK (tenant_id = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid)"
    )


def drop_tenant_isolation_policy_sql(table: str, *, policy_name: str = "tenant_isolation") -> str:
    """Return SQL to drop the ``tenant_isolation`` policy (used in downgrades)."""
    return f"DROP POLICY IF EXISTS {policy_name} ON {table}"


def disable_rls_statements(table: str) -> list[str]:
    """Return SQL statements to disable RLS on ``table`` (used in downgrades)."""
    return [
        f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY",
        f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY",
    ]
