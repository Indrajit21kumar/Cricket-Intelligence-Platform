"""Async engine + session factory + tenant-scoped session context.

The interesting piece is :func:`tenant_session`: it opens an AsyncSession,
runs ``SET LOCAL cip.tenant_id = <uuid>`` on the transaction, and yields
the session. All subsequent queries executed on that session are governed
by the PostgreSQL row-level-security policies in
:mod:`cip_data.rls` — no application-level filtering required.

``SET LOCAL`` scopes the setting to the current transaction, so a rogue
session cannot leak the setting to another. Combined with the RLS policy
``USING (tenant_id = current_setting('cip.tenant_id')::uuid)``, this
enforces tenant isolation *at the database*, not in application code —
the strong form of the Book 3 §4.1 requirement (ENG-001).

An :func:`admin_session` is provided for the narrow set of operations that
legitimately have no tenant scope (tenant provisioning, migrations, ops
scripts). Callers MUST NOT use it from request handlers.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from cip_core import require_tenant_id


def build_engine(database_url: str, *, echo: bool = False) -> AsyncEngine:
    """Construct an :class:`AsyncEngine` bound to ``database_url``.

    ``database_url`` MUST use the ``postgresql+asyncpg://`` scheme.
    ``echo=True`` prints every SQL statement — dev-only.
    """
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError(
            "cip-data requires an asyncpg URL "
            "('postgresql+asyncpg://...'); got: " + database_url.split("://", 1)[0]
        )
    return create_async_engine(
        database_url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


def build_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Build a session factory bound to ``engine``.

    ``expire_on_commit=False`` because CIP services generally re-read via
    fresh queries rather than lazy-loading committed objects.
    """
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def tenant_session(
    session_factory: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """Yield an AsyncSession scoped to a tenant, wrapped in one transaction.

    If ``tenant_id`` is ``None``, the current request's tenant is pulled from
    :mod:`cip_core.context` — raising :class:`MissingTenantError` if none is
    set. That is the intended flow for request handlers, so callers do not
    have to plumb the id through every layer.

    ``SET LOCAL`` binds the tenant to the transaction; RLS policies enforce
    isolation on every query. On exit the transaction commits (or rolls back
    on exception) and the session is closed.
    """
    effective_tenant_id = tenant_id if tenant_id is not None else require_tenant_id()

    async with session_factory() as session, session.begin():
        # SET ROLE to the non-superuser app role so RLS actually applies —
        # the connecting role in many envs (local dev, RDS) is a superuser
        # or table owner which would otherwise bypass RLS silently.
        # SET LOCAL ROLE scopes the change to the transaction.
        await session.execute(text("SET LOCAL ROLE cip_app"))
        # `SET LOCAL` does not accept bind parameters (Postgres parses the
        # value as literal SQL, not as a parameter). set_config(name, value,
        # is_local=true) is the functional equivalent that DOES parameterise —
        # critical here because we're binding a UUID from user context.
        await session.execute(
            text("SELECT set_config('cip.tenant_id', :tid, true)"),
            {"tid": str(effective_tenant_id)},
        )
        yield session


@asynccontextmanager
async def admin_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Yield a NON-tenant-scoped session for admin/provisioning code.

    Use only from ops paths (tenant creation, migrations, background jobs
    that cross tenants intentionally). RLS-protected tables will return
    NOTHING from this session — the policy has no tenant to match — so
    admin code must query the tenants table or use unprotected views.
    Never call this from a request handler.
    """
    async with session_factory() as session, session.begin():
        # Even admin_session runs as the non-superuser app role — otherwise
        # tenant-scoped tables would be visible without a tenant scope,
        # defeating the "no tenant context sees no rows" invariant that
        # the RLS negative tests rely on. tenants (no RLS) remains readable.
        await session.execute(text("SET LOCAL ROLE cip_app"))
        yield session
