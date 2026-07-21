"""Tests for :mod:`cip_core.context`.

Typical: values propagate through async and are visible in nested calls.
Boundary: nested scopes shadow and restore correctly.
Degenerate: no scope set → getters return None; require_tenant_id raises.
Concurrency: parallel asyncio tasks do NOT see each other's context.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from cip_core.context import (
    MissingTenantError,
    correlation_scope,
    get_correlation_id,
    get_tenant_id,
    new_correlation_id,
    require_tenant_id,
    tenant_scope,
)


class TestCorrelationScope:
    def test_uses_supplied_id(self) -> None:
        with correlation_scope("abc-123") as cid:
            assert cid == "abc-123"
            assert get_correlation_id() == "abc-123"

    def test_generates_id_when_absent(self) -> None:
        with correlation_scope() as cid:
            assert cid
            assert len(cid) == 32  # UUID4 hex
            assert get_correlation_id() == cid

    def test_restores_previous_value_on_exit(self) -> None:
        assert get_correlation_id() is None
        with correlation_scope("outer"):
            assert get_correlation_id() == "outer"
            with correlation_scope("inner"):
                assert get_correlation_id() == "inner"
            assert get_correlation_id() == "outer"
        assert get_correlation_id() is None

    def test_restores_on_exception(self) -> None:
        assert get_correlation_id() is None
        with pytest.raises(RuntimeError, match="boom"), correlation_scope("outer"):
            raise RuntimeError("boom")
        assert get_correlation_id() is None


class TestTenantScope:
    def test_binds_and_returns_value(self) -> None:
        tid = uuid.uuid4()
        with tenant_scope(tid):
            assert get_tenant_id() == tid

    def test_nested_scopes_shadow(self) -> None:
        outer = uuid.uuid4()
        inner = uuid.uuid4()
        with tenant_scope(outer):
            with tenant_scope(inner):
                assert get_tenant_id() == inner
            assert get_tenant_id() == outer
        assert get_tenant_id() is None

    def test_require_raises_when_unset(self) -> None:
        assert get_tenant_id() is None
        with pytest.raises(MissingTenantError):
            require_tenant_id()

    def test_require_returns_when_set(self) -> None:
        tid = uuid.uuid4()
        with tenant_scope(tid):
            assert require_tenant_id() == tid


class TestConcurrencyIsolation:
    """Parallel asyncio tasks MUST NOT see each other's context.

    This is the property that makes contextvars safe under FastAPI's
    concurrent request handling — a leak here would be a critical bug.
    """

    async def test_two_tasks_see_independent_tenants(self) -> None:
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        observed: dict[str, uuid.UUID | None] = {}
        gate = asyncio.Event()

        async def worker(name: str, tenant: uuid.UUID) -> None:
            with tenant_scope(tenant):
                # Ensure both tasks are inside a scope before either checks —
                # forces the code to actually rely on contextvars, not
                # sequential ordering.
                gate.set()
                await asyncio.sleep(0)
                observed[name] = get_tenant_id()

        await asyncio.gather(worker("a", tenant_a), worker("b", tenant_b))
        assert observed == {"a": tenant_a, "b": tenant_b}


class TestNewCorrelationId:
    def test_generates_unique_hex(self) -> None:
        ids = {new_correlation_id() for _ in range(100)}
        assert len(ids) == 100
        assert all(len(i) == 32 for i in ids)
        assert all(all(c in "0123456789abcdef" for c in i) for i in ids)
