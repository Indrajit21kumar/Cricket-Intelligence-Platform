"""Request-scoped context: tenant + correlation IDs propagated via contextvars.

Every CIP request or event carries two identifiers threaded through every log
line, span, and outgoing call (Book 2 §4.2, Book 3 §3.3, §8):

- ``correlation_id`` — one stroke/session end-to-end (async + multi-hop safe).
- ``tenant_id``      — the tenant scope every DB query and event is bound to.

Both live in ``contextvars.ContextVar`` so they survive ``asyncio`` context
switches and never leak between concurrent requests. Manipulate them through
the ``tenant_scope`` / ``correlation_scope`` context managers or the FastAPI
middleware in :mod:`cip_core.middleware`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

_correlation_id: ContextVar[str | None] = ContextVar("cip_correlation_id", default=None)
_tenant_id: ContextVar[uuid.UUID | None] = ContextVar("cip_tenant_id", default=None)


class MissingTenantError(RuntimeError):
    """Raised when tenant-scoped code runs without a tenant context set.

    This is a defensive invariant. Any code path that reaches
    :func:`require_tenant_id` without an explicit ``tenant_scope`` upstream is
    a bug — never a runtime condition to be handled.
    """


def get_correlation_id() -> str | None:
    """Return the current request's correlation id, or ``None`` if unset."""
    return _correlation_id.get()


def get_tenant_id() -> uuid.UUID | None:
    """Return the current request's tenant id, or ``None`` if unset."""
    return _tenant_id.get()


def require_tenant_id() -> uuid.UUID:
    """Return the current tenant id, or raise :class:`MissingTenantError`.

    Call this from any code that must not run outside a tenant scope (e.g.
    tenant-scoped DB queries, audit-log writes).
    """
    value = _tenant_id.get()
    if value is None:
        raise MissingTenantError("No tenant_id in the current context")
    return value


def new_correlation_id() -> str:
    """Generate a fresh correlation id (UUID4 hex, unhyphenated)."""
    return uuid.uuid4().hex


@contextmanager
def correlation_scope(correlation_id: str | None = None) -> Iterator[str]:
    """Bind ``correlation_id`` for the duration of the ``with`` block.

    If ``correlation_id`` is ``None`` a fresh one is generated. The previous
    value is restored on exit even if the block raises.
    """
    value = correlation_id if correlation_id is not None else new_correlation_id()
    token = _correlation_id.set(value)
    try:
        yield value
    finally:
        _correlation_id.reset(token)


@contextmanager
def tenant_scope(tenant_id: uuid.UUID) -> Iterator[uuid.UUID]:
    """Bind ``tenant_id`` for the duration of the ``with`` block.

    The previous value is restored on exit even if the block raises.
    """
    token = _tenant_id.set(tenant_id)
    try:
        yield tenant_id
    finally:
        _tenant_id.reset(token)
