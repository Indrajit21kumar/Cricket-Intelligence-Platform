"""Benchmark profile model + selection (M15 Step 2, FR-M15-01, §4, §9).

A :class:`BenchmarkProfile` mirrors one ``benchmark_profiles`` row (Book 5
Ch. 2's profile schema): a versioned set of target metric distributions
scoped to a context. Selection picks the profiles applicable to a stroke —
by shot type, then skill tier / age band / legend style — considering only
RELEASED profiles (NFR-M15-05, AC-M15-06), and only the latest released
version of each ``benchmark_id`` (a profile is versioned data, not edited in
place — FR-M15-08).

Personal-baseline comparison is NOT selected from here: a player's own
history is fetched from M04 (Step 5's ``PersonalBaselineSource``), never
stored as a served benchmark_profiles row, even though Book 5 Ch. 2 lists
``personal`` as one of the four conceptual profile types.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SKILL_TIER = "skill_tier"
AGE_BAND = "age_band"
LEGEND_STYLE = "legend_style"
PERSONAL = "personal"


@dataclass(frozen=True, slots=True)
class BenchmarkProfile:
    """One versioned, scoped set of target metric distributions."""

    benchmark_id: str
    type: str
    scope: Mapping[str, Any] = field(default_factory=dict)
    distributions: Mapping[str, Any] = field(default_factory=dict)
    version: int = 1
    released: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "type": self.type,
            "scope": dict(self.scope),
            "distributions": dict(self.distributions),
            "version": self.version,
            "released": self.released,
        }


def _latest_released(profiles: Sequence[BenchmarkProfile]) -> list[BenchmarkProfile]:
    """Collapse to the latest RELEASED version per benchmark_id."""
    best: dict[str, BenchmarkProfile] = {}
    for profile in profiles:
        if not profile.released:
            continue
        current = best.get(profile.benchmark_id)
        if current is None or profile.version > current.version:
            best[profile.benchmark_id] = profile
    return list(best.values())


def _shot_matches(profile: BenchmarkProfile, shot_type: str) -> bool:
    """A profile with no shot_type in scope applies to any shot; else exact match."""
    scoped_shot = profile.scope.get("shot_type")
    return scoped_shot is None or scoped_shot == shot_type


def select_profiles(
    profiles: Sequence[BenchmarkProfile],
    *,
    shot_type: str,
    skill_tier: str | None = None,
    age_band: str | None = None,
) -> list[BenchmarkProfile]:
    """The applicable, released profiles for one stroke (FR-M15-01).

    Skill-tier profiles require a matching ``skill_tier``; age-band profiles
    require a matching ``age_band``; legend-style profiles are always
    aspirational candidates (no tier/age gating) once shot type matches.
    """
    selected: list[BenchmarkProfile] = []
    for profile in _latest_released(profiles):
        if not _shot_matches(profile, shot_type):
            continue
        if profile.type == SKILL_TIER:
            if skill_tier is not None and profile.scope.get("skill_tier") == skill_tier:
                selected.append(profile)
        elif profile.type == AGE_BAND:
            if age_band is not None and profile.scope.get("age_band") == age_band:
                selected.append(profile)
        elif profile.type == LEGEND_STYLE:
            selected.append(profile)
    return selected
