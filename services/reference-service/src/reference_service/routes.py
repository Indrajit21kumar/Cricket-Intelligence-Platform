"""Demo tenant-scoped endpoint used to prove the full stack is wired.

`POST /v1/demo/echo` takes a message, writes an audit-log row under the
caller's tenant, publishes an event carrying the request's correlation_id,
and returns a summary. Its purpose is to exercise every M01 primitive on
one request path so integration tests can verify:

- ``cip-core`` middleware bound the tenant_id + correlation_id
- ``cip-data.tenant_session`` scoped the DB write to that tenant (RLS)
- ``cip-events`` propagated the correlation_id in the envelope
- ``cip-observability`` correlation_id appears in logs + spans (validated
  via structlog capture in the integration test)
"""

from __future__ import annotations

import uuid
from typing import Annotated

from cip_core import get_correlation_id, require_idempotency_key, require_tenant_id
from cip_data import tenant_session
from cip_events import EventEnvelope
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from reference_service.deps import Deps, get_deps

router = APIRouter(prefix="/v1/demo", tags=["demo"])

DEMO_TOPIC = "cip.demo.echoed"


class EchoRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=200)


class EchoResponse(BaseModel):
    correlation_id: str
    tenant_id: uuid.UUID
    audit_id: uuid.UUID
    published_topic: str


@router.post("/echo", response_model=EchoResponse)
async def echo(
    body: EchoRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> EchoResponse:
    """Write an audit row under the current tenant, publish a demo event."""
    tenant_id = require_tenant_id()
    correlation_id = get_correlation_id() or ""
    audit_id = uuid.uuid4()

    async with tenant_session(deps.session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO audit_log (id, tenant_id, actor, action, entity, "
                "correlation_id, meta) VALUES "
                "(:id, :tid, :actor, :action, :entity, :cid, "
                "cast(:meta as jsonb))"
            ),
            {
                "id": audit_id,
                "tid": tenant_id,
                "actor": "demo",
                "action": "echo",
                "entity": "message",
                "cid": correlation_id,
                "meta": f'{{"message": "{body.message}"}}',
            },
        )

    envelope = EventEnvelope(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        schema_version="1.0.0",
        idempotency_key=idempotency_key,
        payload={"message": body.message, "audit_id": str(audit_id)},
    )
    await deps.event_bus.publish(DEMO_TOPIC, envelope)

    return EchoResponse(
        correlation_id=correlation_id,
        tenant_id=tenant_id,
        audit_id=audit_id,
        published_topic=DEMO_TOPIC,
    )
