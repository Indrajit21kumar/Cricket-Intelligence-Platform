"""Finding assembly + evidence links (M13 §5, Step 6, FR-M13-05, AC-M13-02).

A finding is the platform's core output: {what, why, impact, drill, evidence,
confidence, provisional, provenance}. Each answers "how do you know?" by linking
to the exact triggering metrics (BM/PH ids + values) and the rule (rule_id +
version) that produced it — the backbone of explainability (ENG-005).

The assembler is a pure function of a fired-rule + the fact set it fired against
+ the report-level provisional flag, so every finding is reproducible from those
inputs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from reasoning_service.domain.confidence import (
    combine_confidence,
    combined_provenance,
    is_provisional,
)
from reasoning_service.domain.engine import FiredRule


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    """One triggering metric captured as evidence."""

    metric_id: str
    value: float
    confidence: float
    provenance: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "value": self.value,
            "confidence": self.confidence,
            "provenance": self.provenance,
        }


@dataclass(frozen=True, slots=True)
class Finding:
    """The explained finding a coach reads and the AI coach narrates."""

    finding_id: str
    what: str | None  # the fault
    why: str | None  # the cause
    impact: dict[str, Any]  # the risk (with context + magnitude when given)
    drill: dict[str, Any]  # the correction (name + measurable objective)
    evidence: list[EvidenceLink]
    #: The rule (id + version) that produced this finding — the citation.
    rule_id: str
    rule_version: int
    confidence: float
    provenance: str
    provisional: bool = False
    #: Book 10 evidence tier + validated_by + sources (from M12), so the
    #: report (M14) can render Tier 2/3 honestly and never as validated.
    rule_evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "what": self.what,
            "why": self.why,
            "impact": self.impact,
            "drill": self.drill,
            "evidence": [e.to_dict() for e in self.evidence],
            "citation": {"rule_id": self.rule_id, "version": self.rule_version},
            "confidence": self.confidence,
            "provenance": self.provenance,
            "provisional": self.provisional,
            "rule_evidence": self.rule_evidence,
        }


def _finding_id(rule: FiredRule) -> str:
    return f"F::{rule.rule_id}:v{rule.version}"


def assemble_finding(fired: FiredRule, *, report_provisional: bool) -> Finding:
    """Build a Finding from a fired rule + the report-level provisional flag."""
    triggering = fired.triggering
    evidence = [
        EvidenceLink(
            metric_id=f.metric_id,
            value=f.value,
            confidence=f.confidence,
            provenance=f.provenance,
        )
        for f in triggering
    ]
    return Finding(
        finding_id=_finding_id(fired),
        what=fired.fault,
        why=fired.cause,
        impact=fired.risk,
        drill=fired.drill,
        evidence=evidence,
        rule_id=fired.rule_id,
        rule_version=fired.version,
        confidence=combine_confidence(fired.rule_confidence, triggering),
        provenance=combined_provenance(triggering),
        provisional=is_provisional(triggering, report_provisional=report_provisional),
        rule_evidence=fired.evidence,
    )


def assemble_findings(fired: list[FiredRule], *, report_provisional: bool) -> list[Finding]:
    """Assemble findings for every surviving fired rule, best-confidence first."""
    findings = [assemble_finding(f, report_provisional=report_provisional) for f in fired]
    findings.sort(key=lambda f: f.confidence, reverse=True)
    return findings
