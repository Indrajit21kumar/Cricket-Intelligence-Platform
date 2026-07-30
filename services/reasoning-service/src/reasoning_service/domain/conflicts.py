"""Conflict resolution via M12 precedence (M13 §5, Step 4, FR-M13-03).

When two rules fire on the same stroke with different risks, M12 has (may have)
recorded which one takes precedence. M13 applies that decision: it suppresses the
loser and records which rule won and WHY (AC-M13-04) — the reasoning is never a
silent drop.

A conflict only bites when BOTH its rules actually fired. When M12 recorded no
precedence yet, M13 does not invent one: it keeps both rules and records the
conflict as unresolved, so the ambiguity is visible rather than hidden.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from reasoning_service.domain.engine import FiredRule


@dataclass(frozen=True, slots=True)
class ConflictResolution:
    winner_rule_id: str
    loser_rule_id: str
    reason: str
    resolved: bool


@dataclass(frozen=True, slots=True)
class ResolvedRules:
    surviving: list[FiredRule]
    resolutions: list[ConflictResolution] = field(default_factory=list)


def resolve_conflicts(
    fired: Sequence[FiredRule], conflicts: Sequence[Mapping[str, Any]]
) -> ResolvedRules:
    """Suppress the losing rule of each fired conflict per M12 precedence."""
    fired_ids = {f.rule_id for f in fired}
    suppressed: set[str] = set()
    resolutions: list[ConflictResolution] = []

    for conflict in conflicts:
        rule_a = conflict.get("rule_a")
        rule_b = conflict.get("rule_b")
        # A conflict only matters when both its rules actually fired.
        if rule_a not in fired_ids or rule_b not in fired_ids:
            continue
        precedence = conflict.get("precedence")
        if precedence in (rule_a, rule_b):
            winner = str(precedence)
            loser = str(rule_b if precedence == rule_a else rule_a)
            suppressed.add(loser)
            resolutions.append(
                ConflictResolution(
                    winner_rule_id=winner,
                    loser_rule_id=loser,
                    reason=str(conflict.get("note") or "m12_precedence"),
                    resolved=True,
                )
            )
        else:
            # No precedence recorded — keep both, surface the ambiguity honestly.
            resolutions.append(
                ConflictResolution(
                    winner_rule_id=str(rule_a),
                    loser_rule_id=str(rule_b),
                    reason="unresolved: no precedence recorded in M12",
                    resolved=False,
                )
            )

    surviving = [f for f in fired if f.rule_id not in suppressed]
    return ResolvedRules(surviving=surviving, resolutions=resolutions)
