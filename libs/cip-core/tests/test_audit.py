"""Unit tests for :mod:`cip_core.audit`.

Uses a fake AsyncSession that captures the execute() call — real DB
integration is covered by the reference-service correlation-flow test
(where audit rows are written via the same helper indirectly through the
demo endpoint).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from cip_core.audit import record
from cip_core.context import correlation_scope, tenant_scope


class FakeSession:
    """Captures the last execute() call for assertions."""

    def __init__(self) -> None:
        self.executed: list[tuple[Any, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.executed.append((statement, params))


class TestRecord:
    async def test_writes_row_with_context(self) -> None:
        session = FakeSession()
        tenant_id = uuid.uuid4()
        with correlation_scope("corr-abc"), tenant_scope(tenant_id):
            audit_id = await record(
                session,  # type: ignore[arg-type]
                action="minor.data.exported",
                entity="player:xyz-1",
                actor="user:carol",
                meta={"reason": "guardian request"},
            )

        assert isinstance(audit_id, uuid.UUID)
        assert len(session.executed) == 1
        params = session.executed[0][1]
        assert params["tid"] == tenant_id
        assert params["cid"] == "corr-abc"
        assert params["actor"] == "user:carol"
        assert params["action"] == "minor.data.exported"
        assert params["entity"] == "player:xyz-1"
        assert json.loads(params["meta"]) == {"reason": "guardian request"}
        assert params["id"] == audit_id

    async def test_serialises_missing_meta_as_empty_json(self) -> None:
        session = FakeSession()
        with correlation_scope("c1"), tenant_scope(uuid.uuid4()):
            await record(
                session,  # type: ignore[arg-type]
                action="a",
                entity="e",
                actor="ac",
            )
        assert session.executed[0][1]["meta"] == "{}"

    async def test_serialises_uuid_meta_via_default_str(self) -> None:
        session = FakeSession()
        related_id = uuid.uuid4()
        with correlation_scope("c1"), tenant_scope(uuid.uuid4()):
            await record(
                session,  # type: ignore[arg-type]
                action="a",
                entity="e",
                actor="ac",
                meta={"linked_to": related_id},
            )
        loaded = json.loads(session.executed[0][1]["meta"])
        assert loaded == {"linked_to": str(related_id)}

    async def test_no_tenant_context_raises(self) -> None:
        from cip_core.context import MissingTenantError

        session = FakeSession()
        with correlation_scope("c1"), pytest.raises(MissingTenantError):
            await record(
                session,  # type: ignore[arg-type]
                action="a",
                entity="e",
                actor="ac",
            )
        assert session.executed == []
