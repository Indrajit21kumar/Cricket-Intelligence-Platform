"""Fact assembly — the stroke's facts, typed (M13 §4, Step 2, FR-M13-01).

A "fact" is a metric/physics value plus its confidence and provenance. M13
gathers them from the M10 BiomechanicsReport (BM-01..17), the M11 PhysicsReport
(PH-01..11), and the M09 shot context into one :class:`FactSet` the rule engine
reads. M13 respects provenance and provisionality here so a finding built on an
ESTIMATED or provisional fact can inherit that (Steps 5-6).

An entry with no value (a disabled BM metric, an omitted PH quantity) is NOT a
fact — there is nothing to reason from — so it is dropped, never coerced to
zero.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Fact:
    """One metric/physics value the reasoner can build on."""

    metric_id: str
    value: float
    confidence: float
    provenance: str  # measured | estimated
    provisional: bool = False
    #: A qualitative direction for the metric (e.g. BM-01 -> "outside_off"),
    #: when the upstream carried one. Absent otherwise.
    direction: str | None = None

    @property
    def is_estimated(self) -> bool:
        return self.provenance == "estimated"


@dataclass(frozen=True, slots=True)
class FactSet:
    """Everything the rule engine needs about one stroke."""

    correlation_id: str
    person_id: str | None
    shot_type: str | None
    shot_confidence: float | None
    facts: Mapping[str, Fact]
    phases: Mapping[str, int]
    context: Mapping[str, Any]
    #: True when any source report was provisional (report-level degradation).
    provisional: bool = False

    def fact(self, metric_id: str) -> Fact | None:
        return self.facts.get(metric_id)

    def match_payload(self) -> dict[str, Any]:
        """Shape the facts as M12's /internal/kg/match request (Step 3)."""
        return {
            "metrics": {mid: f.value for mid, f in self.facts.items()},
            "directions": {mid: f.direction for mid, f in self.facts.items() if f.direction},
            "phases": dict(self.phases),
            "shot": self.shot_type,
            "context": dict(self.context),
        }


def _facts_from_metrics(raw: Any) -> dict[str, Fact]:
    """Parse a metrics/quantities map into value-bearing facts only."""
    out: dict[str, Fact] = {}
    if not isinstance(raw, Mapping):
        return out
    for metric_id, entry in raw.items():
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("value")
        if not isinstance(value, int | float):
            continue  # omitted / disabled -> not a fact
        detail = entry.get("detail")
        direction = detail.get("direction") if isinstance(detail, Mapping) else None
        out[str(metric_id)] = Fact(
            metric_id=str(metric_id),
            value=float(value),
            confidence=float(entry.get("confidence", 0.0) or 0.0),
            provenance=str(entry.get("provenance", "measured")),
            provisional=bool(entry.get("provisional", False)),
            direction=str(direction) if direction is not None else None,
        )
    return out


def _int_map(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    return {str(k): v for k, v in raw.items() if isinstance(v, int)}


def build_fact_set(
    *,
    biomechanics: Mapping[str, Any],
    physics: Mapping[str, Any] | None = None,
    shot: Mapping[str, Any] | None = None,
) -> FactSet:
    """Assemble the fact set from the M10/M11/M09 payloads.

    The biomechanics report is the primary source (it carries the shot context +
    phases M10 got from M09); physics adds the PH facts; the optional shot
    payload supplies the delivery context that scopes match-risk rules.
    """
    facts: dict[str, Fact] = {}
    facts.update(_facts_from_metrics(biomechanics.get("metrics")))
    if physics is not None:
        facts.update(_facts_from_metrics(physics.get("quantities")))

    physics = physics or {}
    shot = shot or {}
    shot_type = biomechanics.get("shot_type") or physics.get("shot_type") or shot.get("shot_class")
    shot_confidence = (
        biomechanics.get("shot_confidence")
        if biomechanics.get("shot_confidence") is not None
        else physics.get("shot_confidence")
    )
    raw_context = shot.get("context")
    context: Mapping[str, Any] = raw_context if isinstance(raw_context, Mapping) else {}

    return FactSet(
        correlation_id=str(biomechanics.get("correlation_id", "")),
        person_id=(str(biomechanics["person_id"]) if biomechanics.get("person_id") else None),
        shot_type=shot_type,
        shot_confidence=shot_confidence,
        facts=facts,
        phases=_int_map(biomechanics.get("phase_boundaries")),
        context=context,
        provisional=bool(biomechanics.get("provisional")) or bool(physics.get("provisional")),
    )
