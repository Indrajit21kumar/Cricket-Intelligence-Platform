"""cip-data — SQLAlchemy async base, RLS helpers, migration runners.

Public API stabilised in M01 Step 4.

Typical usage from a service::

    from cip_core import get_settings
    from cip_data import build_engine, build_session_factory, tenant_session

    settings = get_settings()
    engine = build_engine(settings.database_url)
    Session = build_session_factory(engine)

    async with tenant_session(Session) as session:
        # queries here are RLS-scoped to the current request's tenant
        ...
"""

from __future__ import annotations

from cip_data.base import (
    Base,
    TenantScopedMixin,
    TimestampMixin,
    UUIDPKMixin,
)
from cip_data.engine import (
    admin_session,
    build_engine,
    build_session_factory,
    tenant_session,
)
from cip_data.migrations import current, downgrade_base, upgrade_head
from cip_data.rls import (
    TENANT_GUC,
    disable_rls_statements,
    drop_tenant_isolation_policy_sql,
    enable_rls_statements,
    tenant_isolation_policy_sql,
)

__version__ = "0.1.0"

__all__ = [
    "TENANT_GUC",
    "Base",
    "TenantScopedMixin",
    "TimestampMixin",
    "UUIDPKMixin",
    "__version__",
    "admin_session",
    "build_engine",
    "build_session_factory",
    "current",
    "disable_rls_statements",
    "downgrade_base",
    "drop_tenant_isolation_policy_sql",
    "enable_rls_statements",
    "tenant_isolation_policy_sql",
    "tenant_session",
    "upgrade_head",
]
