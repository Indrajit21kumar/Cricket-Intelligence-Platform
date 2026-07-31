"""Team analytics + fair leaderboards (M18 Step 5, FR-M18-04, AC-M18-05)."""

from __future__ import annotations

import uuid

from academy_service.domain.analytics import (
    LeaderboardCandidate,
    aggregate_strengths,
    aggregate_weak_areas,
    build_leaderboard,
    cohort_trend,
)


def _scores(overall: float | None, improvement: float | None) -> dict:
    return {
        "overall": {"value": overall},
        "improvement": {"value": improvement},
    }


class TestCohortTrend:
    def test_empty_roster_has_no_means(self) -> None:
        trend = cohort_trend({})
        assert trend.player_count == 0
        assert trend.scored_count == 0
        assert trend.mean_overall is None
        assert trend.mean_improvement is None

    def test_players_with_no_report_are_excluded_not_zeroed(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        trend = cohort_trend({a: _scores(80.0, 5.0), b: None})
        assert trend.player_count == 2
        assert trend.scored_count == 1
        assert trend.mean_overall == 80.0
        assert trend.mean_improvement == 5.0

    def test_unavailable_score_value_is_excluded_not_zeroed(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        trend = cohort_trend({a: _scores(80.0, 5.0), b: _scores(None, None)})
        assert trend.scored_count == 1
        assert trend.mean_overall == 80.0

    def test_mean_is_computed_across_scored_players(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        trend = cohort_trend({a: _scores(80.0, 4.0), b: _scores(60.0, 8.0)})
        assert trend.mean_overall == 70.0
        assert trend.mean_improvement == 6.0

    def test_to_dict_shape(self) -> None:
        a = uuid.uuid4()
        trend = cohort_trend({a: _scores(80.0, 5.0)})
        assert trend.to_dict() == {
            "player_count": 1,
            "scored_count": 1,
            "mean_overall": 80.0,
            "mean_improvement": 5.0,
        }


class TestAggregateWeakAreas:
    def test_empty_roster_yields_no_counts(self) -> None:
        assert aggregate_weak_areas({}) == []

    def test_counts_players_sharing_a_weak_area(self) -> None:
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        insights = {
            a: {"weak_areas": ["rule-1"], "strengths": []},
            b: {"weak_areas": ["rule-1", "rule-2"], "strengths": []},
            c: {"weak_areas": [], "strengths": []},
        }
        result = aggregate_weak_areas(insights)
        assert [r.to_dict() for r in result] == [
            {"key": "rule-1", "player_count": 2},
            {"key": "rule-2", "player_count": 1},
        ]

    def test_ties_are_broken_alphabetically_for_determinism(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        insights = {
            a: {"weak_areas": ["rule-b"], "strengths": []},
            b: {"weak_areas": ["rule-a"], "strengths": []},
        }
        result = aggregate_weak_areas(insights)
        assert [r.key for r in result] == ["rule-a", "rule-b"]


class TestAggregateStrengths:
    def test_counts_players_sharing_a_strength(self) -> None:
        a, b = uuid.uuid4(), uuid.uuid4()
        insights = {
            a: {"weak_areas": [], "strengths": ["metric-1"]},
            b: {"weak_areas": [], "strengths": ["metric-1"]},
        }
        result = aggregate_strengths(insights)
        assert [r.to_dict() for r in result] == [{"key": "metric-1", "player_count": 2}]


def _candidate(
    *,
    score: float,
    skill_tier: str | None = "intermediate",
    age_band: str | None = "U14",
    opted_in: bool = True,
    display_name: str | None = None,
) -> LeaderboardCandidate:
    return LeaderboardCandidate(
        person_id=uuid.uuid4(),
        display_name=display_name,
        score=score,
        skill_tier=skill_tier,
        age_band=age_band,
        opted_in=opted_in,
    )


class TestBuildLeaderboard:
    def test_ranks_by_score_descending(self) -> None:
        low = _candidate(score=50.0)
        high = _candidate(score=90.0)
        board = build_leaderboard([low, high], skill_tier="intermediate", age_band="U14")
        assert [e.person_id for e in board] == [high.person_id, low.person_id]
        assert [e.rank for e in board] == [1, 2]

    def test_opted_out_players_are_excluded(self) -> None:
        opted_out = _candidate(score=99.0, opted_in=False)
        opted_in = _candidate(score=10.0, opted_in=True)
        board = build_leaderboard([opted_out, opted_in], skill_tier="intermediate", age_band="U14")
        assert [e.person_id for e in board] == [opted_in.person_id]

    def test_only_the_matching_cohort_is_ranked(self) -> None:
        matching = _candidate(score=50.0, skill_tier="intermediate", age_band="U14")
        other_tier = _candidate(score=99.0, skill_tier="advanced", age_band="U14")
        other_band = _candidate(score=99.0, skill_tier="intermediate", age_band="U16")
        board = build_leaderboard(
            [matching, other_tier, other_band], skill_tier="intermediate", age_band="U14"
        )
        assert [e.person_id for e in board] == [matching.person_id]

    def test_empty_pool_yields_empty_leaderboard(self) -> None:
        assert build_leaderboard([], skill_tier="intermediate", age_band="U14") == []
