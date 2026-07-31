"""Fault prioritisation: impact x fixability x stage-readiness (M17 Step 3, FR-M17-02).

``score = impact x fixability x readiness(stage)``

- **Impact**: ``PENALTY_PER_FINDING x finding.confidence`` — the same cost
  model M14's ``scoring.py`` uses to deduct a category score for a finding,
  independently redeclared here (not imported cross-service) — a firm
  finding costs more, exactly the "how much does this matter" signal a
  report already has to compute.
- **Fixability**: how confidently actionable the fault is, from its
  evidence provenance — a directly MEASURED fault is more confidently
  fixable than one only ESTIMATED or MODELLED (an explicit, versioned
  mapping; no other established "fixability" concept exists in this
  codebase to draw from).
- **Readiness(stage)**: whether the player's inferred stage (Step 2) is
  ready for this fault's category. Book 1 Ch. 4.7 frames Cognitive as
  foundational-drill territory, Associative as refinement, Autonomous as
  peak execution/tactical — mapped onto a MINIMAL metric-to-category
  classification (not M14's full scoring catalogue, just enough to tell
  these three groups apart) since the spec names the *kind* of readiness,
  not numeric weights.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

BALANCE = "balance"
FOOTWORK = "footwork"
TIMING = "timing"
POWER = "power"
TECHNIQUE = "technique"

PRIORITIZATION_MODEL_VERSION = "fault-priority-1.0.0"

#: Mirrors M14 scoring.py's PENALTY_PER_FINDING (same value, independently
#: scoped) — a firm finding costs more, the "how much does this matter" signal.
PENALTY_PER_FINDING = 20.0

FIXABILITY_BY_PROVENANCE: dict[str, float] = {
    "measured": 1.0,
    "estimated": 0.7,
    "modelled": 0.5,
}
DEFAULT_FIXABILITY = 0.5

#: A minimal metric -> category map for readiness classification only.
METRIC_FOCUS_CATEGORY: dict[str, str] = {
    "BM-01": BALANCE,
    "BM-14": BALANCE,
    "BM-16": BALANCE,
    "BM-07": FOOTWORK,
    "BM-08": FOOTWORK,
    "BM-11": TIMING,
    "BM-17": TIMING,
    "PH-01": POWER,
    "PH-06": POWER,
    "PH-07": POWER,
    "PH-08": POWER,
    "PH-09": POWER,
    "PH-10": POWER,
}
#: Anything not in the map above is treated as general technique/refinement.
DEFAULT_FOCUS_CATEGORY = TECHNIQUE

#: Book 1 Ch. 4.7: Cognitive = foundational body control; Associative =
#: refinement of technique/timing; Autonomous = peak execution.
STAGE_FOCUS: dict[str, tuple[str, ...]] = {
    "cognitive": (BALANCE, FOOTWORK),
    "associative": (TECHNIQUE, TIMING),
    "autonomous": (POWER, TECHNIQUE),
}
FOCUS_READINESS = 1.0
OFF_FOCUS_READINESS = 0.6


@dataclass(frozen=True, slots=True)
class PrioritizedFault:
    """One finding's priority score, with its components exposed (NFR-M17-04)."""

    finding_id: str
    score: float
    impact: float
    fixability: float
    readiness: float
    categories: tuple[str, ...]
    model_version: str = PRIORITIZATION_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "finding_id": self.finding_id,
            "score": self.score,
            "impact": self.impact,
            "fixability": self.fixability,
            "readiness": self.readiness,
            "categories": list(self.categories),
            "model_version": self.model_version,
        }


def _finding_metric_ids(finding: Mapping[str, Any]) -> list[str]:
    evidence = finding.get("evidence", [])
    if not isinstance(evidence, Sequence):
        return []
    return [
        e["metric_id"]
        for e in evidence
        if isinstance(e, Mapping) and isinstance(e.get("metric_id"), str)
    ]


def _finding_categories(finding: Mapping[str, Any]) -> tuple[str, ...]:
    metric_ids = _finding_metric_ids(finding)
    if not metric_ids:
        return (DEFAULT_FOCUS_CATEGORY,)
    categories = {METRIC_FOCUS_CATEGORY.get(mid, DEFAULT_FOCUS_CATEGORY) for mid in metric_ids}
    return tuple(sorted(categories))


def _impact(finding: Mapping[str, Any]) -> float:
    confidence = finding.get("confidence")
    return PENALTY_PER_FINDING * (confidence if isinstance(confidence, int | float) else 1.0)


def _fixability(finding: Mapping[str, Any]) -> float:
    provenance = finding.get("provenance")
    if not isinstance(provenance, str):
        return DEFAULT_FIXABILITY
    return FIXABILITY_BY_PROVENANCE.get(provenance, DEFAULT_FIXABILITY)


def _readiness(categories: Sequence[str], stage: str) -> float:
    focus = STAGE_FOCUS.get(stage, ())
    return (
        FOCUS_READINESS
        if any(category in focus for category in categories)
        else OFF_FOCUS_READINESS
    )


def prioritize_faults(
    findings: Sequence[Mapping[str, Any]], *, stage: str
) -> list[PrioritizedFault]:
    """Rank findings by impact x fixability x stage-readiness, highest first."""
    prioritized = []
    for finding in findings:
        finding_id = finding.get("finding_id")
        if not isinstance(finding_id, str):
            continue
        categories = _finding_categories(finding)
        impact = _impact(finding)
        fixability = _fixability(finding)
        readiness = _readiness(categories, stage)
        prioritized.append(
            PrioritizedFault(
                finding_id=finding_id,
                score=impact * fixability * readiness,
                impact=impact,
                fixability=fixability,
                readiness=readiness,
                categories=categories,
            )
        )
    return sorted(prioritized, key=lambda p: p.score, reverse=True)
