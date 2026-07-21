"""Standard event envelope every CIP topic carries (Book 2 §4.2, Book 3 §3.3).

Every message on every topic — from ``video.uploaded`` to ``report.ready`` —
wraps its domain payload in :class:`EventEnvelope`. The envelope is the
contract that makes the pipeline debuggable end-to-end:

- ``correlation_id`` threads one stroke/session through every stage.
- ``tenant_id`` binds every event to a tenant scope; consumers use it to
  build the tenant-scoped DB session before writing anything.
- ``schema_version`` lets the schema registry enforce backward compatibility
  on consumer side.
- ``produced_at`` supports stage-latency SLO tracking (Book 3 §8).
- ``idempotency_key`` is the deduplication anchor for the idempotent consumer.
- ``provenance`` is optional on generic events, required on any event that
  carries analytical values (Book 0 §8 Trust Doctrine).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from cip_events.provenance import Provenance


def _utcnow() -> datetime:
    return datetime.now(UTC)


class EventEnvelope(BaseModel):
    """Wire envelope wrapping every CIP event payload."""

    model_config = ConfigDict(
        extra="forbid",  # unknown fields = schema drift = fail fast
        populate_by_name=True,
    )

    #: Stable identifier for one stroke/session across every pipeline stage.
    correlation_id: str = Field(..., min_length=1, max_length=200)
    #: Tenant scope every downstream write must be bound to.
    tenant_id: uuid.UUID
    #: Semantic version of the payload schema (e.g. "1.0.0", "2.1.0").
    schema_version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    #: When the producer emitted the event. Consumers use this for lag/SLO.
    produced_at: datetime = Field(default_factory=_utcnow)
    #: Dedup anchor for the idempotent consumer.
    idempotency_key: str = Field(..., min_length=1, max_length=200)
    #: measured / estimated / modelled for analytical events. Optional on
    #: non-analytical events (e.g. user.registered).
    provenance: Provenance | None = None
    #: Confidence for ``estimated``/``modelled`` values (0.0 to 1.0).
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    #: Domain payload — whatever the producing service defined.
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_serializer("tenant_id")
    def _serialise_tenant_id(self, value: uuid.UUID) -> str:
        return str(value)

    @field_serializer("produced_at")
    def _serialise_produced_at(self, value: datetime) -> str:
        # ISO-8601 with 'Z' suffix (Kafka consumers in other languages parse this
        # more reliably than pydantic's default '+00:00').
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
