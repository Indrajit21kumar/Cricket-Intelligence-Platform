"""Personal-baseline comparison (M15 Step 5, FR-M15-06, AC-M15-07)."""

from __future__ import annotations

import asyncio

from benchmark_service.domain.personal_baseline import (
    IMPROVED,
    REGRESSED,
    STABLE,
    UNKNOWN_DIRECTION,
    FakePersonalBaselineSource,
    PersonalBaseline,
    compare_to_baseline,
)


def _fact(value: float, confidence: float = 0.9) -> dict:
    return {"value": value, "confidence": confidence, "provenance": "measured"}


class TestCompareToBaseline:
    def test_lower_is_better_metric_improving_is_reported_as_improved(self) -> None:
        # BM-01 head stability: lower is better. Improved 10cm -> 8cm.
        facts = {"BM-01": _fact(8.0)}
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        results = compare_to_baseline(facts, baselines)
        assert len(results) == 1
        assert results[0].direction == IMPROVED
        assert results[0].delta == -2.0

    def test_lower_is_better_metric_regressing_is_reported_as_regressed(self) -> None:
        facts = {"BM-01": _fact(13.0)}
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        results = compare_to_baseline(facts, baselines)
        assert results[0].direction == REGRESSED

    def test_higher_is_better_metric_improving_is_reported_as_improved(self) -> None:
        # BM-04 X-factor: higher is better.
        facts = {"BM-04": _fact(30.0)}
        baselines = [PersonalBaseline(metric_id="BM-04", mean=25.0)]
        results = compare_to_baseline(facts, baselines)
        assert results[0].direction == IMPROVED

    def test_no_change_is_stable(self) -> None:
        facts = {"BM-01": _fact(10.0)}
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        results = compare_to_baseline(facts, baselines)
        assert results[0].direction == STABLE

    def test_metric_without_a_documented_direction_is_honestly_unknown(self) -> None:
        facts = {"BM-05": _fact(6.0)}
        baselines = [PersonalBaseline(metric_id="BM-05", mean=5.0)]
        results = compare_to_baseline(facts, baselines)
        assert results[0].direction == UNKNOWN_DIRECTION

    def test_metric_with_no_baseline_is_skipped(self) -> None:
        facts = {"BM-01": _fact(8.0)}
        assert compare_to_baseline(facts, []) == []

    def test_baseline_with_no_matching_fact_is_skipped(self) -> None:
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        assert compare_to_baseline({}, baselines) == []

    def test_confidence_propagates_from_the_fact(self) -> None:
        facts = {"BM-01": _fact(8.0, confidence=0.77)}
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        results = compare_to_baseline(facts, baselines)
        assert results[0].confidence == 0.77


class TestFakePersonalBaselineSource:
    def test_no_history_returns_empty_list(self) -> None:
        source = FakePersonalBaselineSource()
        assert asyncio.run(source.load("player-1")) == []

    def test_set_baselines_is_returned_for_that_player_only(self) -> None:
        source = FakePersonalBaselineSource()
        baselines = [PersonalBaseline(metric_id="BM-01", mean=10.0)]
        source.set_baselines("player-1", baselines)
        assert asyncio.run(source.load("player-1")) == baselines
        assert asyncio.run(source.load("player-2")) == []
