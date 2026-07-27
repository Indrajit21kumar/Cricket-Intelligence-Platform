"""Fact-pattern matcher — facts -> applicable rules (M12 Step 5, §11, FR-M12-05).

M13 hands M12 the facts of one stroke (the M10/M11 metrics, phases, shot, and
context) and asks which rules fire. A rule fires when ALL of its conditions are
satisfied by the facts (AND); a condition whose fact is absent fails, so a rule
never fires on missing evidence — the honest default.

Matching runs over the RELEASED snapshots only (the immutable pinned graph), so
a draft or approved-but-unreleased rule can never reach reasoning (AC-M12-02).
The matched rules come back with their confidence + governance so M13 can weigh
and cite them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from knowledge_service.domain.rule_schema import (
    KIND_CONTEXT,
    KIND_METRIC,
    KIND_PHASE,
    KIND_SHOT,
    NUMERIC_OPS,
)

_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


@dataclass(frozen=True, slots=True)
class MatchFacts:
    """The facts of one stroke, as M13 supplies them."""

    metrics: Mapping[str, float] = field(default_factory=dict)
    #: qualitative directions per metric (e.g. BM-01 -> "outside_off").
    directions: Mapping[str, str] = field(default_factory=dict)
    phases: Mapping[str, Any] = field(default_factory=dict)
    shot: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> MatchFacts:
        metrics_raw = payload.get("metrics", {})
        metrics = {
            str(k): float(v)
            for k, v in (metrics_raw.items() if isinstance(metrics_raw, Mapping) else [])
            if isinstance(v, int | float)
        }
        directions_raw = payload.get("directions", {})
        directions = (
            {str(k): str(v) for k, v in directions_raw.items()}
            if isinstance(directions_raw, Mapping)
            else {}
        )
        phases = payload.get("phases", {})
        context = payload.get("context", {})
        return cls(
            metrics=metrics,
            directions=directions,
            phases=phases if isinstance(phases, Mapping) else {},
            shot=payload.get("shot"),
            context=context if isinstance(context, Mapping) else {},
        )


@dataclass(frozen=True, slots=True)
class MatchedRule:
    rule_id: str
    version: int
    confidence: float | None
    fault: str | None
    cause: str | None
    risk: dict[str, Any]
    drill: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "version": self.version,
            "confidence": self.confidence,
            "fault": self.fault,
            "cause": self.cause,
            "risk": self.risk,
            "drill": self.drill,
        }


def _condition_holds(cond: Mapping[str, Any], facts: MatchFacts) -> bool:
    kind = cond.get("kind")
    field_ = cond.get("field", "")
    op = cond.get("op", "eq")
    value = cond.get("value")

    if kind == KIND_METRIC:
        if op == "direction":
            return facts.directions.get(field_) == value
        observed = facts.metrics.get(field_)
        if observed is None or op not in NUMERIC_OPS or not isinstance(value, int | float):
            return False
        return _COMPARATORS[op](observed, float(value))

    if kind == KIND_SHOT:
        return facts.shot is not None and facts.shot == value

    if kind == KIND_PHASE:
        observed_phase = facts.phases.get(field_)
        if observed_phase is None:
            return False
        if (
            op in NUMERIC_OPS
            and isinstance(observed_phase, int | float)
            and isinstance(value, int | float)
        ):
            return _COMPARATORS[op](float(observed_phase), float(value))
        return bool(observed_phase == value)

    if kind == KIND_CONTEXT:
        observed_ctx = facts.context.get(field_)
        if op == "in" and isinstance(value, list):
            return observed_ctx in value
        return observed_ctx is not None and observed_ctx == value

    return False


def rule_matches(conditions: Sequence[Mapping[str, Any]], facts: MatchFacts) -> bool:
    """A rule fires only when EVERY condition is satisfied (AND)."""
    return bool(conditions) and all(_condition_holds(c, facts) for c in conditions)


def select_matches(
    released_snapshots: Sequence[Mapping[str, Any]], facts: MatchFacts
) -> list[MatchedRule]:
    """Return the released rules whose conditions the facts satisfy, best first."""
    matched: list[MatchedRule] = []
    for row in released_snapshots:
        snapshot = row.get("snapshot", {})
        conditions = snapshot.get("conditions", [])
        if not isinstance(conditions, list):
            continue
        if rule_matches(conditions, facts):
            matched.append(
                MatchedRule(
                    rule_id=str(row.get("rule_id", snapshot.get("rule_id", ""))),
                    version=int(row.get("version", snapshot.get("version", 0))),
                    confidence=snapshot.get("confidence"),
                    fault=snapshot.get("fault"),
                    cause=snapshot.get("cause"),
                    risk=snapshot.get("risk", {}),
                    drill=snapshot.get("drill", {}),
                )
            )
    # Highest-confidence first; None confidence sinks to the bottom.
    matched.sort(key=lambda m: m.confidence if m.confidence is not None else -1.0, reverse=True)
    return matched
