"""Team analytics + fair leaderboards (M18 Step 5, FR-M18-04, AC-M18-05).

Three independent aggregations over the roster, each a pure function of
per-player data the caller has already gathered — no cricket analysis is
computed here, only counting and ranking of what upstream modules already
produced:

- :func:`cohort_trend` — mean overall score / improvement across players
  who have a report. A player with no report yet (or a report whose
  ``overall``/``improvement`` is itself unavailable) is excluded from the
  mean rather than counted as zero — the same "never fabricate" discipline
  used throughout this platform.
- :func:`aggregate_weak_areas` / :func:`aggregate_strengths` — how many
  players currently share each recurring weak area / strength, most
  common first.
- :func:`build_leaderboard` — ranks players by score, but ONLY within a
  single (skill_tier, age_band) cohort and ONLY among players who opted
  in. "Fair" reuses M15's own skill_tier/age_band benchmark axes rather
  than inventing a new fairness notion; "opt-in" means a player absent
  from the opt-in set is excluded, never defaulted onto the board.
"""

from __future__ import annotations

import statistics
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CohortTrend:
    """Roster-wide score trend, honest about how many players contributed."""

    player_count: int
    scored_count: int
    mean_overall: float | None
    mean_improvement: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_count": self.player_count,
            "scored_count": self.scored_count,
            "mean_overall": self.mean_overall,
            "mean_improvement": self.mean_improvement,
        }


@dataclass(frozen=True, slots=True)
class CohortInsightCount:
    """How many players currently share one recurring weak area / strength."""

    key: str
    player_count: int

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "player_count": self.player_count}


@dataclass(frozen=True, slots=True)
class LeaderboardCandidate:
    """One player's leaderboard inputs — pre-gathered, not looked up here."""

    person_id: uuid.UUID
    display_name: str | None
    score: float
    skill_tier: str | None
    age_band: str | None
    opted_in: bool


@dataclass(frozen=True, slots=True)
class LeaderboardEntry:
    """One ranked leaderboard row."""

    rank: int
    person_id: uuid.UUID
    display_name: str | None
    score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "person_id": str(self.person_id),
            "display_name": self.display_name,
            "score": self.score,
        }


def _score_value(scores: Mapping[str, Any] | None, field: str) -> float | None:
    if scores is None:
        return None
    entry = scores.get(field)
    if not isinstance(entry, Mapping):
        return None
    value = entry.get("value")
    return value if isinstance(value, int | float) else None


def cohort_trend(scores_by_player: Mapping[uuid.UUID, Mapping[str, Any] | None]) -> CohortTrend:
    """Mean overall/improvement across players who have a usable value."""
    overall_values = [
        v for v in (_score_value(s, "overall") for s in scores_by_player.values()) if v is not None
    ]
    improvement_values = [
        v
        for v in (_score_value(s, "improvement") for s in scores_by_player.values())
        if v is not None
    ]
    return CohortTrend(
        player_count=len(scores_by_player),
        scored_count=len(overall_values),
        mean_overall=statistics.fmean(overall_values) if overall_values else None,
        mean_improvement=statistics.fmean(improvement_values) if improvement_values else None,
    )


def _aggregate_counts(
    insights_by_player: Mapping[uuid.UUID, Mapping[str, Any]], field: str
) -> list[CohortInsightCount]:
    counts: dict[str, int] = {}
    for insights in insights_by_player.values():
        raw = insights.get(field, [])
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, str):
                counts[item] = counts.get(item, 0) + 1
    return [
        CohortInsightCount(key=key, player_count=count)
        for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def aggregate_weak_areas(
    insights_by_player: Mapping[uuid.UUID, Mapping[str, Any]],
) -> list[CohortInsightCount]:
    return _aggregate_counts(insights_by_player, "weak_areas")


def aggregate_strengths(
    insights_by_player: Mapping[uuid.UUID, Mapping[str, Any]],
) -> list[CohortInsightCount]:
    return _aggregate_counts(insights_by_player, "strengths")


def build_leaderboard(
    candidates: Sequence[LeaderboardCandidate],
    *,
    skill_tier: str | None,
    age_band: str | None,
) -> list[LeaderboardEntry]:
    """Rank opted-in players within one skill_tier/age_band cohort, highest score first."""
    fair_pool = [
        c
        for c in candidates
        if c.opted_in and c.skill_tier == skill_tier and c.age_band == age_band
    ]
    ranked = sorted(fair_pool, key=lambda c: (-c.score, str(c.person_id)))
    return [
        LeaderboardEntry(
            rank=position,
            person_id=c.person_id,
            display_name=c.display_name,
            score=c.score,
        )
        for position, c in enumerate(ranked, start=1)
    ]
