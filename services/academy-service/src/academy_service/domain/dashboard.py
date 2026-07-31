"""Coach dashboard composition (M18 Step 4, FR-M18-03, AC-M18-04).

A dashboard is one player's scores (M14), DNA traits (M16), and active
plan (M17) assembled side by side for their coach — nothing more. M18
computes no cricket analysis of its own (§3.2): every field here is a
pass-through of what the source module already produced. A source with
nothing for this player yet contributes an honestly-absent field (``None``
or ``{}``), never a fabricated placeholder — the same "never fabricate"
discipline used throughout this platform.

"Progress" (FR-M18-03's fourth dashboard element, alongside scores/DNA/
plans) is not a fifth computation: M14's ``Scores.improvement`` entry
already carries it, so it travels inside ``scores`` rather than being
recomputed here.

Whether THIS coach may see THIS player's dashboard at all is Step 7's
access-control enforcement — this module composes what it's handed,
assuming that check has already passed.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PlayerDashboard:
    """One player's composed dashboard."""

    person_id: uuid.UUID
    display_name: str | None
    scores: Mapping[str, Any] | None
    dna_traits: Mapping[str, Mapping[str, Any]]
    active_plan: Mapping[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": str(self.person_id),
            "display_name": self.display_name,
            "scores": dict(self.scores) if self.scores is not None else None,
            "dna_traits": {key: dict(value) for key, value in self.dna_traits.items()},
            "active_plan": dict(self.active_plan) if self.active_plan is not None else None,
        }


def compose_dashboard(
    *,
    person_id: uuid.UUID,
    display_name: str | None,
    scores: Mapping[str, Any] | None,
    dna_traits: Mapping[str, Mapping[str, Any]],
    active_plan: Mapping[str, Any] | None,
) -> PlayerDashboard:
    """Assemble one player's dashboard from its four independent sources.

    Pure aggregation — no derived scoring, ranking, or interpretation.
    """
    return PlayerDashboard(
        person_id=person_id,
        display_name=display_name,
        scores=scores,
        dna_traits=dna_traits,
        active_plan=active_plan,
    )
