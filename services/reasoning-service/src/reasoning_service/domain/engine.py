"""The generic rule engine (M13 §5, Step 3, FR-M13-02).

M13 does not re-implement matching — M12 owns the knowledge and does the
fact-pattern match against its pinned graph (Book 0 §5: improving coaching is a
data change in M12, not code in M13). So a "fired rule" here is a rule M12
returned as applicable, annotated with the exact facts that triggered it — the
metric conditions whose fields are present in the fact set. Those triggering
facts are the evidence basis (Step 6) and drive the confidence combination
(Step 5).

Because M12 already guaranteed every condition matched, the engine's job is to
carry the rule forward with its triggering facts resolved; it never invents a
rule (FR-M13-08 — no unsupported finding).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from reasoning_service.domain.facts import Fact, FactSet

KIND_METRIC = "metric"


@dataclass(frozen=True, slots=True)
class FiredRule:
    """A matched M12 rule + the facts that triggered it."""

    rule_id: str
    version: int
    rule_confidence: float | None
    fault: str | None
    cause: str | None
    risk: dict[str, Any]
    drill: dict[str, Any]
    evidence: dict[str, Any]
    #: The facts (BM/PH) whose metric conditions the rule matched on.
    triggering: tuple[Fact, ...] = field(default_factory=tuple)

    @property
    def metric_ids(self) -> list[str]:
        return [f.metric_id for f in self.triggering]


def _triggering_facts(conditions: Sequence[Any], fact_set: FactSet) -> list[Fact]:
    """The facts referenced by the rule's METRIC conditions (its evidence)."""
    triggering: list[Fact] = []
    seen: set[str] = set()
    for cond in conditions:
        if not isinstance(cond, Mapping) or cond.get("kind") != KIND_METRIC:
            continue
        metric_id = cond.get("field")
        if not isinstance(metric_id, str) or metric_id in seen:
            continue
        fact = fact_set.fact(metric_id)
        if fact is not None:
            triggering.append(fact)
            seen.add(metric_id)
    return triggering


def fire(fact_set: FactSet, matched_rules: Sequence[Mapping[str, Any]]) -> list[FiredRule]:
    """Turn M12's matched rules into fired rules with their triggering facts."""
    fired: list[FiredRule] = []
    for rule in matched_rules:
        conditions = rule.get("conditions", [])
        triggering = _triggering_facts(conditions if isinstance(conditions, list) else [], fact_set)
        fired.append(
            FiredRule(
                rule_id=str(rule.get("rule_id", "")),
                version=int(rule.get("version", 0)),
                rule_confidence=rule.get("confidence"),
                fault=rule.get("fault"),
                cause=rule.get("cause"),
                risk=rule.get("risk", {}) if isinstance(rule.get("risk"), Mapping) else {},
                drill=rule.get("drill", {}) if isinstance(rule.get("drill"), Mapping) else {},
                evidence=rule.get("evidence", {})
                if isinstance(rule.get("evidence"), Mapping)
                else {},
                triggering=tuple(triggering),
            )
        )
    return fired
