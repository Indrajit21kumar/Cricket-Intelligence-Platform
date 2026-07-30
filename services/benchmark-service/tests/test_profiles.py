"""Benchmark profile selection (M15 Step 2, FR-M15-01)."""

from __future__ import annotations

from benchmark_service.domain.profiles import (
    AGE_BAND,
    LEGEND_STYLE,
    SKILL_TIER,
    BenchmarkProfile,
    select_profiles,
)


def _tier_profile(
    skill_tier: str = "advanced",
    shot_type: str | None = "cover_drive",
    version: int = 1,
    released: bool = True,
) -> BenchmarkProfile:
    scope = {"skill_tier": skill_tier}
    if shot_type is not None:
        scope["shot_type"] = shot_type
    return BenchmarkProfile(
        benchmark_id=f"BN-TIER-{skill_tier.upper()}-COVERDRIVE",
        type=SKILL_TIER,
        scope=scope,
        distributions={"BM-01": {"mean": 10.0, "spread": 2.0}},
        version=version,
        released=released,
    )


def _age_profile(age_band: str = "u14", released: bool = True) -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id=f"BN-AGE-{age_band.upper()}",
        type=AGE_BAND,
        scope={"age_band": age_band, "shot_type": "cover_drive"},
        released=released,
    )


def _legend_profile(name: str = "high-backlift", released: bool = True) -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id=f"BN-LEGEND-{name.upper()}",
        type=LEGEND_STYLE,
        scope={},
        released=released,
    )


class TestSelectProfiles:
    def test_matching_skill_tier_is_selected(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced")]
        selected = select_profiles(profiles, shot_type="cover_drive", skill_tier="advanced")
        assert len(selected) == 1

    def test_non_matching_skill_tier_is_excluded(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced")]
        selected = select_profiles(profiles, shot_type="cover_drive", skill_tier="beginner")
        assert selected == []

    def test_no_skill_tier_given_excludes_tier_profiles(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced")]
        assert select_profiles(profiles, shot_type="cover_drive") == []

    def test_wrong_shot_type_is_excluded(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced", shot_type="cover_drive")]
        selected = select_profiles(profiles, shot_type="pull_shot", skill_tier="advanced")
        assert selected == []

    def test_profile_with_no_shot_scope_applies_to_any_shot(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced", shot_type=None)]
        selected = select_profiles(profiles, shot_type="pull_shot", skill_tier="advanced")
        assert len(selected) == 1

    def test_matching_age_band_is_selected(self) -> None:
        profiles = [_age_profile(age_band="u14")]
        selected = select_profiles(profiles, shot_type="cover_drive", age_band="u14")
        assert len(selected) == 1

    def test_legend_style_is_always_a_candidate_regardless_of_tier(self) -> None:
        profiles = [_legend_profile()]
        selected = select_profiles(profiles, shot_type="cover_drive")
        assert len(selected) == 1

    def test_unreleased_profile_is_never_selected(self) -> None:
        profiles = [_tier_profile(skill_tier="advanced", released=False)]
        selected = select_profiles(profiles, shot_type="cover_drive", skill_tier="advanced")
        assert selected == []

    def test_only_the_latest_released_version_is_kept(self) -> None:
        older = _tier_profile(skill_tier="advanced", version=1, released=True)
        newer = _tier_profile(skill_tier="advanced", version=2, released=True)
        selected = select_profiles([older, newer], shot_type="cover_drive", skill_tier="advanced")
        assert len(selected) == 1
        assert selected[0].version == 2

    def test_an_unreleased_newer_version_does_not_shadow_the_released_older_one(self) -> None:
        released_v1 = _tier_profile(skill_tier="advanced", version=1, released=True)
        draft_v2 = _tier_profile(skill_tier="advanced", version=2, released=False)
        selected = select_profiles(
            [released_v1, draft_v2], shot_type="cover_drive", skill_tier="advanced"
        )
        assert len(selected) == 1
        assert selected[0].version == 1

    def test_no_profiles_at_all_selects_nothing(self) -> None:
        assert select_profiles([], shot_type="cover_drive", skill_tier="advanced") == []
