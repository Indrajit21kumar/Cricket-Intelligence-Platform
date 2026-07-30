"""Match-risk output (M13 §6, Step 7, FR-M13-06, AC-M13-06).

Where fired rules carry a Delivery context and a risk magnitude, M13 produces
the tactical output: "against a full delivery outside off, this fault raises
inside-edge probability ~X%." It is labelled **MODELLED** (Book 0 §8) with its
rule/context, so the report never presents it as a measurement.

This is the seed of the Match Intelligence engine (Book 0 §7 Engine 4). In v1 it
is rule-driven; a data-driven, contextual-risk-learned version is a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reasoning_service.domain.findings import Finding

PROVENANCE_MODELLED = "modelled"


@dataclass(frozen=True, slots=True)
class MatchRiskItem:
    """One risk-carrying finding, surfaced for the tactical layer."""

    finding_id: str
    rule_id: str
    rule_version: int
    statement: str
    context: str | None
    magnitude: str | None
    confidence: float
    provenance: str = PROVENANCE_MODELLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "citation": {"rule_id": self.rule_id, "version": self.rule_version},
            "statement": self.statement,
            "context": self.context,
            "magnitude": self.magnitude,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class MatchRisk:
    """The tactical summary served to M14 alongside the findings."""

    items: list[MatchRiskItem] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provenance": PROVENANCE_MODELLED,
            "items": [item.to_dict() for item in self.items],
        }


def build_match_risk(findings: list[Finding]) -> MatchRisk:
    """Extract the risk-carrying findings; every item is labelled MODELLED."""
    items: list[MatchRiskItem] = []
    for finding in findings:
        impact = finding.impact
        if not isinstance(impact, dict):
            continue
        statement = impact.get("statement")
        # No risk statement -> nothing tactical to surface.
        if not isinstance(statement, str) or not statement.strip():
            continue
        items.append(
            MatchRiskItem(
                finding_id=finding.finding_id,
                rule_id=finding.rule_id,
                rule_version=finding.rule_version,
                statement=statement,
                context=impact.get("context"),
                magnitude=impact.get("magnitude"),
                confidence=finding.confidence,
            )
        )
    return MatchRisk(items=items)
