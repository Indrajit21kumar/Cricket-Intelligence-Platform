"""Input source adapters (M14 Step 2+, §10).

report-service assembles a report from several upstream reads. Each is a seam,
following the "adapters + fakes, defer real infra" pattern used throughout the
platform (M05's VideoProcessor/ProfileClient, M07's BatDetector, ...): a real
implementation is deferred, a deterministic fake lets the assembly + guardrail
logic be built and tested now.

- :class:`HistorySource` — the player's own longitudinal baseline (M04 Cricket
  DNA), for the Improvement score (Book 4 Ch. 8). M04 exists as a module, but
  the cross-service fetch is deferred like every other adapter in this build.
- :class:`LegendSource` — M15's ``benchmark.compared`` payload for the Legend
  comparison view (Step 4). M15 does not exist as a built service yet (only
  its spec), so this is a fan-in read keyed by correlation_id, same as the
  other cross-module fetches in this build.
- :class:`MetricsSource` — M10 biomechanics + M11 physics metrics for a
  stroke (Step 8), fetched by correlation_id the same way M13's FactSource
  fetched them for reasoning.
- :class:`VideoArtefactSource` — the M05 clip ref + M06/M07 pose/bat artefact
  refs + M09 phase boundaries a stroke needs for annotated-video rendering
  (Step 8).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class PlayerHistory:
    """A player's prior baseline for one CIP-STD metric-derived score."""

    metric_key: str
    baseline_value: float
    baseline_confidence: float


class HistorySource(Protocol):
    async def load(self, person_id: str) -> list[PlayerHistory]:
        """The player's stored baselines, or [] when there is no history yet."""
        ...


class FakeHistorySource:
    """In-process history source holding baselines for dev + tests."""

    def __init__(self) -> None:
        self.histories: dict[str, list[PlayerHistory]] = {}

    def set_history(self, person_id: str, history: list[PlayerHistory]) -> None:
        self.histories[person_id] = history

    async def load(self, person_id: str) -> list[PlayerHistory]:
        return self.histories.get(person_id, [])


class LegendSource(Protocol):
    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        """M15's comparison payload for this stroke, or None if not yet produced."""
        ...


class FakeLegendSource:
    """In-process legend-comparison source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.comparisons: dict[str, Mapping[str, Any]] = {}

    def set_comparison(self, correlation_id: str, comparison: Mapping[str, Any]) -> None:
        self.comparisons[correlation_id] = comparison

    async def load(self, correlation_id: str) -> Mapping[str, Any] | None:
        return self.comparisons.get(correlation_id)


@dataclass(frozen=True, slots=True)
class MetricsBundle:
    """The M10 biomechanics + M11 physics metrics for one stroke."""

    biomechanics: dict[str, Any] = field(default_factory=dict)
    physics: dict[str, Any] | None = None


class MetricsSource(Protocol):
    async def load(self, correlation_id: str) -> MetricsBundle:
        """M10/M11 metrics for this stroke; empty biomechanics if not yet available."""
        ...


class FakeMetricsSource:
    """In-process metrics source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.bundles: dict[str, MetricsBundle] = {}

    def set_metrics(self, correlation_id: str, bundle: MetricsBundle) -> None:
        self.bundles[correlation_id] = bundle

    async def load(self, correlation_id: str) -> MetricsBundle:
        return self.bundles.get(correlation_id, MetricsBundle())


@dataclass(frozen=True, slots=True)
class VideoArtefacts:
    """What Step 3's video rendering needs for one stroke."""

    clip_ref: str
    pose_artefact_ref: str | None
    bat_artefact_ref: str | None
    phases: dict[str, int] = field(default_factory=dict)


class VideoArtefactSource(Protocol):
    async def load(self, correlation_id: str) -> VideoArtefacts | None:
        """The clip + pose/bat artefact refs + phases for this stroke, or None."""
        ...


class FakeVideoArtefactSource:
    """In-process video-artefact source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.artefacts: dict[str, VideoArtefacts] = {}

    def set_artefacts(self, correlation_id: str, artefacts: VideoArtefacts) -> None:
        self.artefacts[correlation_id] = artefacts

    async def load(self, correlation_id: str) -> VideoArtefacts | None:
        return self.artefacts.get(correlation_id)
