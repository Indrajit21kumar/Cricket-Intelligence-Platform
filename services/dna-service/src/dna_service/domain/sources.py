"""Input source adapters (M16 Step 2, §8).

dna-service assembles a session's trait evidence from several upstream
reads. Each is a seam, following the "adapters + fakes, defer real infra"
pattern used throughout this platform: a real implementation is deferred, a
deterministic fake lets the pipeline be built and tested now.

- :class:`ReportScoresSource` — M14's ``Scores.to_dict()`` for a stroke
  (Performance-trait evidence, ``domain/evidence.py``).
- :class:`FindingsSource` — M13's findings for a stroke (recurring-fault
  weak_areas / clean-execution strengths, Step 5).
- :class:`BenchmarkPositionSource` — M15's per-metric benchmark
  classifications for a stroke (tier-relative standing, Step 5).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class ReportScoresSource(Protocol):
    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        """M14's Scores.to_dict() for this stroke, or None if not yet produced."""
        ...


class FakeReportScoresSource:
    """In-process report-scores source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.scores: dict[str, Mapping[str, Any]] = {}

    def set_scores(self, correlation_id: str, scores: Mapping[str, Any]) -> None:
        self.scores[correlation_id] = scores

    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        return self.scores.get(correlation_id)


class FindingsSource(Protocol):
    async def load(self, correlation_id: str) -> list[Mapping[str, Any]]:
        """M13's findings for this stroke, or [] when there are none."""
        ...


class FakeFindingsSource:
    """In-process findings source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.findings: dict[str, list[Mapping[str, Any]]] = {}

    def set_findings(self, correlation_id: str, findings: list[Mapping[str, Any]]) -> None:
        self.findings[correlation_id] = findings

    async def load(self, correlation_id: str) -> list[Mapping[str, Any]]:
        return self.findings.get(correlation_id, [])


class BenchmarkPositionSource(Protocol):
    async def load(self, correlation_id: str) -> Sequence[Mapping[str, Any]]:
        """M15's per-metric comparison classifications for this stroke, or []."""
        ...


class FakeBenchmarkPositionSource:
    """In-process benchmark-position source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.positions: dict[str, Sequence[Mapping[str, Any]]] = {}

    def set_position(self, correlation_id: str, per_metric: Sequence[Mapping[str, Any]]) -> None:
        self.positions[correlation_id] = per_metric

    async def load(self, correlation_id: str) -> Sequence[Mapping[str, Any]]:
        return self.positions.get(correlation_id, [])
