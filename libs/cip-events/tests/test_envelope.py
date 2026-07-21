"""Unit tests for :mod:`cip_events.envelope`."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from cip_events.envelope import EventEnvelope
from cip_events.provenance import Provenance
from pydantic import ValidationError


def _valid_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "correlation_id": "corr-1",
        "tenant_id": uuid.uuid4(),
        "schema_version": "1.0.0",
        "idempotency_key": "idem-1",
    }
    base.update(overrides)
    return base


class TestRequiredFields:
    def test_minimal_valid_envelope(self) -> None:
        env = EventEnvelope(**_valid_kwargs())  # type: ignore[arg-type]
        assert env.correlation_id == "corr-1"
        assert env.schema_version == "1.0.0"
        assert env.provenance is None
        assert env.payload == {}

    def test_missing_correlation_id(self) -> None:
        kwargs = _valid_kwargs()
        kwargs.pop("correlation_id")
        with pytest.raises(ValidationError):
            EventEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_missing_tenant_id(self) -> None:
        kwargs = _valid_kwargs()
        kwargs.pop("tenant_id")
        with pytest.raises(ValidationError):
            EventEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_missing_schema_version(self) -> None:
        kwargs = _valid_kwargs()
        kwargs.pop("schema_version")
        with pytest.raises(ValidationError):
            EventEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_missing_idempotency_key(self) -> None:
        kwargs = _valid_kwargs()
        kwargs.pop("idempotency_key")
        with pytest.raises(ValidationError):
            EventEnvelope(**kwargs)  # type: ignore[arg-type]


class TestFieldValidation:
    def test_bad_schema_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope(**_valid_kwargs(schema_version="v1"))  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        """extra='forbid' guarantees schema drift is caught at boundaries."""
        kwargs = _valid_kwargs()
        kwargs["unexpected"] = "field"
        with pytest.raises(ValidationError):
            EventEnvelope(**kwargs)  # type: ignore[arg-type]

    def test_confidence_out_of_range(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope(**_valid_kwargs(confidence=1.5))  # type: ignore[arg-type]
        with pytest.raises(ValidationError):
            EventEnvelope(**_valid_kwargs(confidence=-0.1))  # type: ignore[arg-type]

    def test_empty_correlation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope(**_valid_kwargs(correlation_id=""))  # type: ignore[arg-type]

    def test_too_long_correlation_id_rejected(self) -> None:
        with pytest.raises(ValidationError):
            EventEnvelope(**_valid_kwargs(correlation_id="x" * 201))  # type: ignore[arg-type]


class TestProvenance:
    def test_measured(self) -> None:
        env = EventEnvelope(**_valid_kwargs(provenance=Provenance.MEASURED))  # type: ignore[arg-type]
        assert env.provenance is Provenance.MEASURED

    def test_string_value_accepted(self) -> None:
        env = EventEnvelope(**_valid_kwargs(provenance="estimated"))  # type: ignore[arg-type]
        assert env.provenance is Provenance.ESTIMATED


class TestSerialisation:
    def test_json_roundtrip(self) -> None:
        original = EventEnvelope(
            **_valid_kwargs(
                provenance=Provenance.ESTIMATED,
                confidence=0.87,
                payload={"foo": "bar"},
            )
        )  # type: ignore[arg-type]
        raw = original.model_dump_json()
        parsed = EventEnvelope.model_validate_json(raw)
        assert parsed == original

    def test_produced_at_serialises_with_z_suffix(self) -> None:
        env = EventEnvelope(
            **_valid_kwargs(
                produced_at=datetime(2026, 7, 21, 12, 0, tzinfo=UTC),
            )
        )  # type: ignore[arg-type]
        raw = json.loads(env.model_dump_json())
        assert raw["produced_at"].endswith("Z")
        assert "+00:00" not in raw["produced_at"]

    def test_tenant_id_serialises_as_string(self) -> None:
        tid = uuid.uuid4()
        env = EventEnvelope(**_valid_kwargs(tenant_id=tid))  # type: ignore[arg-type]
        raw = json.loads(env.model_dump_json())
        assert raw["tenant_id"] == str(tid)
