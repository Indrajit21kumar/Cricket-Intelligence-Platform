"""Input source adapters — Fakes for dev + tests (M14 Step 2/4/8)."""

from __future__ import annotations

import asyncio

from report_service.domain.sources import (
    FakeHistorySource,
    FakeLegendSource,
    FakeMetricsSource,
    FakeVideoArtefactSource,
    MetricsBundle,
    PlayerHistory,
    VideoArtefacts,
)


class TestFakeHistorySource:
    def test_no_history_returns_empty_list(self) -> None:
        source = FakeHistorySource()
        assert asyncio.run(source.load("player-1")) == []

    def test_set_history_is_returned_for_that_player_only(self) -> None:
        source = FakeHistorySource()
        history = [PlayerHistory(metric_key="BM-01", baseline_value=10.0, baseline_confidence=0.9)]
        source.set_history("player-1", history)
        assert asyncio.run(source.load("player-1")) == history
        assert asyncio.run(source.load("player-2")) == []


class TestFakeLegendSource:
    def test_no_comparison_returns_none(self) -> None:
        source = FakeLegendSource()
        assert asyncio.run(source.load("stroke-1")) is None

    def test_set_comparison_is_returned_for_that_stroke_only(self) -> None:
        source = FakeLegendSource()
        comparison = {"styles": []}
        source.set_comparison("stroke-1", comparison)
        assert asyncio.run(source.load("stroke-1")) == comparison
        assert asyncio.run(source.load("stroke-2")) is None


class TestFakeMetricsSource:
    def test_no_metrics_returns_empty_bundle(self) -> None:
        source = FakeMetricsSource()
        bundle = asyncio.run(source.load("stroke-1"))
        assert bundle.biomechanics == {}
        assert bundle.physics is None

    def test_set_metrics_is_returned_for_that_stroke_only(self) -> None:
        source = FakeMetricsSource()
        bundle = MetricsBundle(
            biomechanics={"BM-01": {"value": 5.0}}, physics={"PH-01": {"value": 1.0}}
        )
        source.set_metrics("stroke-1", bundle)
        assert asyncio.run(source.load("stroke-1")) == bundle
        loaded = asyncio.run(source.load("stroke-2"))
        assert loaded.biomechanics == {}


class TestFakeVideoArtefactSource:
    def test_no_artefacts_returns_none(self) -> None:
        source = FakeVideoArtefactSource()
        assert asyncio.run(source.load("stroke-1")) is None

    def test_set_artefacts_is_returned_for_that_stroke_only(self) -> None:
        source = FakeVideoArtefactSource()
        artefacts = VideoArtefacts(
            clip_ref="clip://abc",
            pose_artefact_ref="pose://abc",
            bat_artefact_ref=None,
            phases={"impact": 14},
        )
        source.set_artefacts("stroke-1", artefacts)
        assert asyncio.run(source.load("stroke-1")) == artefacts
        assert asyncio.run(source.load("stroke-2")) is None
