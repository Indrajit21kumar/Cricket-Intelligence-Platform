"""Canonical rule schema + validation (M12 §5, Book 4 Ch. 6, AC-M12-01).

A rule is a Fault -> Cause -> Risk -> Drill statement with the *conditions* that
make it fire, an authored *confidence*, and governance metadata. This module
parses a rule payload into typed objects and rejects anything that is not a
well-formed rule — the store never holds a half-formed rule.

A ``condition`` is a single predicate over a stroke's facts, of four kinds:
  - ``metric``  — a threshold or direction on a CIP-STD metric (BM-xx / PH-xx)
  - ``phase``   — a fact about a phase boundary
  - ``shot``    — the shot must be a given class
  - ``context`` — a delivery/context fact
The matcher (Step 5) evaluates these against M10/M11 facts; here we only ensure
each is structurally sound.

Evidence metadata (Book 10: ``sources[]``, ``evidence_tier``, ``validated_by``,
``contradicts_tradition``) is layered on in Step 8; this module is the core
Fault->Cause->Risk->Drill contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from knowledge_service.domain.lifecycle import STATUS_DRAFT, STATUSES

# --- condition vocabulary ---
KIND_METRIC = "metric"
KIND_PHASE = "phase"
KIND_SHOT = "shot"
KIND_CONTEXT = "context"
CONDITION_KINDS = frozenset({KIND_METRIC, KIND_PHASE, KIND_SHOT, KIND_CONTEXT})

#: Numeric comparison operators + the non-numeric ones (set membership, a
#: qualitative direction like "outside_off", and equality).
NUMERIC_OPS = frozenset({">", ">=", "<", "<=", "==", "!="})
OTHER_OPS = frozenset({"in", "direction", "eq"})
OPS = NUMERIC_OPS | OTHER_OPS

_RULE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*(-[A-Z0-9]+){1,3}$")  # e.g. KG-RISK-002
_METRIC_ID_RE = re.compile(r"^[A-Z]{2,3}-[0-9A-Za-z]+$")  # e.g. BM-17, PH-06


class RuleValidationError(ValueError):
    """A rule payload was not a well-formed canonical rule."""


@dataclass(frozen=True, slots=True)
class Condition:
    kind: str
    #: The subject: a metric id (metric), phase name (phase), or context key.
    field: str
    op: str
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "field": self.field, "op": self.op, "value": self.value}


@dataclass(frozen=True, slots=True)
class Risk:
    statement: str
    context: str | None = None  # the Delivery it applies against
    magnitude: str | None = None  # e.g. "+~25%"

    def to_dict(self) -> dict[str, Any]:
        return {"statement": self.statement, "context": self.context, "magnitude": self.magnitude}


@dataclass(frozen=True, slots=True)
class Drill:
    name: str
    objective: str  # a MEASURABLE objective (Book 4 Ch. 6)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "objective": self.objective}


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    version: int
    conditions: tuple[Condition, ...]
    fault: str
    cause: str
    risk: Risk
    drill: Drill
    confidence: float
    status: str = STATUS_DRAFT
    author: str | None = None
    reviewer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "conditions": [c.to_dict() for c in self.conditions],
            "fault": self.fault,
            "cause": self.cause,
            "risk": self.risk.to_dict(),
            "drill": self.drill.to_dict(),
            "confidence": self.confidence,
            "status": self.status,
            "author": self.author,
            "reviewer": self.reviewer,
        }


def _validate_condition(raw: Any, index: int, errors: list[str]) -> Condition | None:
    where = f"conditions[{index}]"
    if not isinstance(raw, dict):
        errors.append(f"{where} must be an object")
        return None
    kind = raw.get("kind")
    if kind not in CONDITION_KINDS:
        errors.append(f"{where}.kind must be one of {sorted(CONDITION_KINDS)}")
        return None

    field_ = raw.get("field", "")
    op = raw.get("op", "eq")
    value = raw.get("value")

    if op not in OPS:
        errors.append(f"{where}.op {op!r} is not a known operator")
    if kind == KIND_METRIC:
        if not isinstance(field_, str) or not _METRIC_ID_RE.match(field_):
            errors.append(f"{where}.field {field_!r} is not a CIP-STD metric id")
        if op in NUMERIC_OPS and not isinstance(value, int | float):
            errors.append(f"{where} numeric op {op!r} needs a numeric value")
    elif kind == KIND_SHOT:
        if not value:
            errors.append(f"{where} shot condition needs a value")
    elif kind in (KIND_PHASE, KIND_CONTEXT) and not field_:
        errors.append(f"{where} {kind} condition needs a field")

    if errors and errors[-1].startswith(where):
        return None
    return Condition(kind=kind, field=str(field_), op=str(op), value=value)


def _validate_risk(raw: Any, errors: list[str]) -> Risk | None:
    if not isinstance(raw, dict):
        errors.append("risk must be an object with at least a statement")
        return None
    statement = raw.get("statement")
    if not isinstance(statement, str) or not statement.strip():
        errors.append("risk.statement is required")
        return None
    return Risk(
        statement=statement,
        context=raw.get("context"),
        magnitude=raw.get("magnitude"),
    )


def _validate_drill(raw: Any, errors: list[str]) -> Drill | None:
    if not isinstance(raw, dict):
        errors.append("drill must be an object with a name + measurable objective")
        return None
    name = raw.get("name")
    objective = raw.get("objective")
    if not isinstance(name, str) or not name.strip():
        errors.append("drill.name is required")
    if not isinstance(objective, str) or not objective.strip():
        errors.append("drill.objective (a measurable objective) is required")
    if errors and errors[-1].startswith("drill"):
        return None
    return Drill(name=str(name), objective=str(objective))


def validate_rule(payload: dict[str, Any]) -> Rule:
    """Parse + validate a rule payload; raise RuleValidationError if malformed."""
    errors: list[str] = []

    rule_id = payload.get("rule_id", "")
    if not isinstance(rule_id, str) or not _RULE_ID_RE.match(rule_id):
        errors.append("rule_id must look like 'KG-RISK-002'")

    version = payload.get("version", 1)
    if not isinstance(version, int) or version < 1:
        errors.append("version must be an integer >= 1")

    raw_conditions = payload.get("conditions")
    conditions: list[Condition] = []
    if not isinstance(raw_conditions, list) or not raw_conditions:
        errors.append("conditions must be a non-empty list")
    else:
        for i, raw in enumerate(raw_conditions):
            cond = _validate_condition(raw, i, errors)
            if cond is not None:
                conditions.append(cond)

    fault = payload.get("fault")
    if not isinstance(fault, str) or not fault.strip():
        errors.append("fault is required")
    cause = payload.get("cause")
    if not isinstance(cause, str) or not cause.strip():
        errors.append("cause is required")

    risk = _validate_risk(payload.get("risk"), errors)
    drill = _validate_drill(payload.get("drill"), errors)

    raw_confidence = payload.get("confidence")
    confidence_value = 0.0
    if isinstance(raw_confidence, int | float) and 0.0 <= float(raw_confidence) <= 1.0:
        confidence_value = float(raw_confidence)
    else:
        errors.append("confidence must be a number in [0, 1]")

    status = payload.get("status", STATUS_DRAFT)
    if status not in STATUSES:
        errors.append(f"status must be one of {sorted(STATUSES)}")

    if errors or risk is None or drill is None:
        # risk/drill are None only when an error was already recorded; the
        # combined guard keeps mypy happy without a strippable assert.
        raise RuleValidationError("; ".join(errors) or "invalid rule")

    return Rule(
        rule_id=str(rule_id),
        version=int(version),
        conditions=tuple(conditions),
        fault=str(fault),
        cause=str(cause),
        risk=risk,
        drill=drill,
        confidence=confidence_value,
        status=str(status),
        author=payload.get("author"),
        reviewer=payload.get("reviewer"),
    )


#: The spec's worked example (M12 §5, KG-RISK-002) — proves a canonical rule
#: loads and validates end to end.
WORKED_EXAMPLE: dict[str, Any] = {
    "rule_id": "KG-RISK-002",
    "version": 1,
    "conditions": [
        # Front-foot plant late (ground-contact timing beyond the threshold).
        {"kind": KIND_METRIC, "field": "BM-17", "op": ">", "value": 50.0},
        # Head drifts outside off.
        {"kind": KIND_METRIC, "field": "BM-01", "op": "direction", "value": "outside_off"},
    ],
    "fault": "head falling outside off",
    "cause": "weight staying back",
    "risk": {
        "statement": "LBW / inside edge",
        "context": "full outside-off delivery",
        "magnitude": "+~25%",
    },
    "drill": {
        "name": "closed-shoulder drill",
        "objective": "keep head over front knee at plant on 8/10 balls",
    },
    "confidence": 0.91,
}
