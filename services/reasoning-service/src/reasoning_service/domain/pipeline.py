"""The pure reasoning pipeline (M13 §5).

One pure function ties the module together, with no DB or event bus:

    facts (M10+M11+M09) + rules (M12 pinned) + conflicts (M12)
      -> fire matching rules (Step 3)
      -> resolve conflicts by M12 precedence (Step 4)
      -> assemble findings with combined confidence + evidence links (Steps 5-6)
      -> compute match-risk labelled MODELLED (Step 7)
      -> assemble the ReasoningResult

Because reasoning is a pure function of (facts, rules, conflicts, kg_version),
it is deterministic: identical inputs -> identical output (NFR-M13-02,
AC-M13-07). And the "no unsupported finding" rule (FR-M13-08) is enforced by
construction: the only findings emitted are the ones a released rule (from M12)
matched, so a draft rule cannot possibly fire.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from reasoning_service.domain.conflicts import (
    ConflictResolution,
    resolve_conflicts,
)
from reasoning_service.domain.engine import fire
from reasoning_service.domain.facts import FactSet
from reasoning_service.domain.findings import Finding, assemble_findings
from reasoning_service.domain.match_risk import MatchRisk, build_match_risk

SCHEMA_VERSION = "analysis.reasoned/1.0"


@dataclass(frozen=True, slots=True)
class ReasoningResult:
    """The full reasoning output for one stroke."""

    correlation_id: str
    person_id: str | None
    shot_type: str | None
    shot_confidence: float | None
    kg_version: str
    findings: list[Finding]
    match_risk: MatchRisk
    resolutions: list[ConflictResolution] = field(default_factory=list)
    provisional: bool = False
    schema_version: str = SCHEMA_VERSION

    def findings_payload(self) -> list[dict[str, Any]]:
        return [f.to_dict() for f in self.findings]

    def match_risk_payload(self) -> dict[str, Any]:
        return self.match_risk.to_dict()

    def quality_payload(self) -> dict[str, Any]:
        """Reasoning-level quality: kg_version + conflict resolutions."""
        return {
            "kg_version": self.kg_version,
            "provisional": self.provisional,
            "resolutions": [
                {
                    "winner": r.winner_rule_id,
                    "loser": r.loser_rule_id,
                    "reason": r.reason,
                    "resolved": r.resolved,
                }
                for r in self.resolutions
            ],
        }


def reason(
    fact_set: FactSet,
    matched_rules: Sequence[dict[str, Any]],
    *,
    conflicts: Sequence[dict[str, Any]] = (),
    kg_version: str,
) -> ReasoningResult:
    """Execute the reasoning pipeline over one stroke's facts + M12 rules."""
    fired = fire(fact_set, matched_rules)
    resolved = resolve_conflicts(fired, conflicts)
    findings = assemble_findings(resolved.surviving, report_provisional=fact_set.provisional)
    return ReasoningResult(
        correlation_id=fact_set.correlation_id,
        person_id=fact_set.person_id,
        shot_type=fact_set.shot_type,
        shot_confidence=fact_set.shot_confidence,
        kg_version=kg_version,
        findings=findings,
        match_risk=build_match_risk(findings),
        resolutions=resolved.resolutions,
        provisional=fact_set.provisional or any(f.provisional for f in findings),
    )
