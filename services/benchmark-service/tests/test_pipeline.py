"""Comparison pipeline — pure orchestration (M15 Step 7)."""

from __future__ import annotations

from benchmark_service.domain.personal_baseline import PersonalBaseline
from benchmark_service.domain.pipeline import compute_comparison
from benchmark_service.domain.profiles import AGE_BAND, LEGEND_STYLE, SKILL_TIER, BenchmarkProfile


def _fact(value: float, confidence: float = 0.9) -> dict:
    return {"value": value, "confidence": confidence, "provenance": "measured"}


def _tier_profile(version: int = 1) -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id="BN-TIER-ADV-COVERDRIVE",
        type=SKILL_TIER,
        scope={"skill_tier": "advanced", "shot_type": "cover_drive"},
        distributions={"BM-01": {"range": [4.0, 8.0], "spread": 2.0}},
        version=version,
        released=True,
    )


def _age_profile() -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id="BN-AGE-U14",
        type=AGE_BAND,
        scope={"age_band": "u14", "shot_type": "cover_drive"},
        distributions={"BM-01": {"range": [4.0, 8.0], "spread": 2.0}},
        released=True,
    )


def _legend_profile() -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id="BN-LEGEND-HIGHBACKLIFT",
        type=LEGEND_STYLE,
        scope={"label": "high-backlift style"},
        distributions={"BM-01": {"range": [4.0, 8.0], "spread": 2.0}},
        version=2,
        released=True,
    )


class TestComputeComparison:
    def test_skill_tier_is_the_primary_comparison_target(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=[_tier_profile(), _age_profile()],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band="u14",
        )
        assert len(result.per_metric) == 1
        assert "BN-TIER-ADV-COVERDRIVE@1" in result.benchmark_version

    def test_falls_back_to_age_band_when_no_skill_tier_selected(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=[_age_profile()],
            shot_type="cover_drive",
            skill_tier=None,
            age_band="u14",
        )
        assert len(result.per_metric) == 1
        assert "BN-AGE-U14" in result.benchmark_version

    def test_no_selected_profiles_yields_empty_comparison(self) -> None:
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts={"BM-01": _fact(6.0)},
            all_profiles=[],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        )
        assert result.per_metric == []
        assert result.legend_similarity is None
        assert result.benchmark_version == "none"

    def test_legend_similarity_is_included_when_scoreable(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=[_tier_profile(), _legend_profile()],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        )
        assert result.legend_similarity is not None
        assert result.legend_similarity["styles"][0]["style_label"] == "high-backlift style"
        assert "disclaimer" in result.legend_similarity
        assert "BN-LEGEND-HIGHBACKLIFT@2" in result.benchmark_version

    def test_personal_baseline_is_merged_into_per_metric(self) -> None:
        facts = {"BM-01": _fact(8.0)}
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id="player-1",
            facts=facts,
            all_profiles=[_tier_profile()],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
            personal_baselines=baselines,
        )
        entry = result.per_metric[0]
        assert entry["personal_baseline"] is not None
        assert entry["personal_baseline"]["direction"] == "improved"

    def test_metric_with_no_personal_baseline_has_none(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=[_tier_profile()],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        )
        assert result.per_metric[0]["personal_baseline"] is None

    def test_confidence_is_the_mean_of_primary_comparisons(self) -> None:
        facts = {"BM-01": _fact(6.0, confidence=0.6)}
        result = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=[_tier_profile()],
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        )
        assert result.confidence == 0.6

    def test_result_is_reproducible_given_same_inputs(self) -> None:
        facts = {"BM-01": _fact(6.0)}
        profiles = [_tier_profile(), _legend_profile()]
        a = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=profiles,
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        ).to_dict()
        b = compute_comparison(
            correlation_id="stroke-1",
            person_id=None,
            facts=facts,
            all_profiles=profiles,
            shot_type="cover_drive",
            skill_tier="advanced",
            age_band=None,
        ).to_dict()
        assert a == b
