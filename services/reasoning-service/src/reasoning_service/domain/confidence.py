"""Confidence combination + trust propagation (M13 §5, Step 5, FR-M13-04/07).

A finding is only as trustworthy as the weakest link in the chain that produced
it. So M13 combines:

- **finding confidence** = rule confidence x the weakest triggering metric's
  confidence. A firm rule resting on a shaky measurement is a shaky finding.
- **provisional** propagates: a finding built on any provisional metric — or on
  a report that was provisional overall — is itself provisional.
- **provenance** propagates: a finding that leans on an ESTIMATED physics
  quantity is itself ESTIMATED, never presented as measured. Book 0 §8 does not
  stop at the metric — it follows the metric into the conclusion.
"""

from __future__ import annotations

from collections.abc import Sequence

from reasoning_service.domain.facts import Fact

PROVENANCE_MEASURED = "measured"
PROVENANCE_ESTIMATED = "estimated"


def combine_confidence(rule_confidence: float | None, triggering: Sequence[Fact]) -> float:
    """rule confidence x the weakest triggering metric confidence, clamped."""
    rule = rule_confidence if rule_confidence is not None else 1.0
    metric = min((f.confidence for f in triggering), default=1.0)
    return round(max(0.0, min(1.0, rule * metric)), 3)


def is_provisional(triggering: Sequence[Fact], *, report_provisional: bool) -> bool:
    """A finding is provisional if any triggering fact is, or the report was."""
    return report_provisional or any(f.provisional for f in triggering)


def combined_provenance(triggering: Sequence[Fact]) -> str:
    """ESTIMATED if any triggering fact is estimated, else MEASURED."""
    return PROVENANCE_ESTIMATED if any(f.is_estimated for f in triggering) else PROVENANCE_MEASURED
