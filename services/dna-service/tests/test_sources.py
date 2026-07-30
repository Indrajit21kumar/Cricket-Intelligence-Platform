"""Input source adapters — Fakes for dev + tests (M16 Step 2)."""

from __future__ import annotations

import asyncio

from dna_service.domain.sources import (
    FakeBenchmarkPositionSource,
    FakeFindingsSource,
    FakeReportScoresSource,
)


class TestFakeReportScoresSource:
    def test_no_scores_returns_none(self) -> None:
        source = FakeReportScoresSource()
        assert asyncio.run(source.load("stroke-1")) is None

    def test_set_scores_is_returned_for_that_stroke_only(self) -> None:
        source = FakeReportScoresSource()
        scores = {"timing": {"value": 80.0}}
        source.set_scores("stroke-1", scores)
        assert asyncio.run(source.load("stroke-1")) == scores
        assert asyncio.run(source.load("stroke-2")) is None


class TestFakeFindingsSource:
    def test_no_findings_returns_empty_list(self) -> None:
        source = FakeFindingsSource()
        assert asyncio.run(source.load("stroke-1")) == []

    def test_set_findings_is_returned_for_that_stroke_only(self) -> None:
        source = FakeFindingsSource()
        findings = [{"finding_id": "F::KG-A:v1"}]
        source.set_findings("stroke-1", findings)
        assert asyncio.run(source.load("stroke-1")) == findings
        assert asyncio.run(source.load("stroke-2")) == []


class TestFakeBenchmarkPositionSource:
    def test_no_position_returns_empty_sequence(self) -> None:
        source = FakeBenchmarkPositionSource()
        assert asyncio.run(source.load("stroke-1")) == []

    def test_set_position_is_returned_for_that_stroke_only(self) -> None:
        source = FakeBenchmarkPositionSource()
        per_metric = [{"metric_id": "BM-01", "classification": "within"}]
        source.set_position("stroke-1", per_metric)
        assert asyncio.run(source.load("stroke-1")) == per_metric
        assert asyncio.run(source.load("stroke-2")) == []
