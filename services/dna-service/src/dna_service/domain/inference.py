"""Strengths/weak_areas inference from recurring evidence (M16 Step 5, FR-M16-05).

A single session's fault is noise; a fault that RECURS across sessions is a
weak area worth a coach's attention. This module maintains a small
occurrence-count state per rule_id/metric_id, serialised into the trait's
own stored value — the same string M04 persists and returns next session
via ``DNAReader`` — and re-derives the CURRENT recurring set each time,
crossing :data:`RECURRENCE_THRESHOLD` sessions. This keeps M16 stateless
between sessions: everything it needs is the trait's own prior value.

Style tags (backlift, stance, dominant_side) are Book 4/M16's other
descriptive trait group, but this build has no established, measured signal
for any of them — no backlift-angle metric exists in the M10 catalogue, and
no shot-side-frequency source is wired anywhere. Inventing a threshold to
classify them would repeat the exact mistake this project's "never
fabricate a formula the codebase hasn't earned" principle exists to
prevent — the same reasoning Step 2 applied to ``trait.aggression``, and
M14's ``HIGHER_IS_BETTER`` allow-list applied to Improvement. They are
deliberately left uncomputed in v1 rather than guessed at.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

#: Sessions a rule_id/metric_id must recur in before it counts as a weak
#: area / strength — an explicit, versioned threshold.
RECURRENCE_THRESHOLD = 2
INFERENCE_MODEL_VERSION = "dna-inference-1.0.0"

WEAK_AREAS_TRAIT_KEY = "weak.areas"
STRENGTHS_TRAIT_KEY = "trait.strengths"


@dataclass(frozen=True, slots=True)
class RecurrenceState:
    """Occurrence counts keyed by rule_id or metric_id — the trait's stored value."""

    counts: Mapping[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(dict(sorted(self.counts.items())))

    @classmethod
    def from_json(cls, raw: str | None) -> RecurrenceState:
        if not raw:
            return cls()
        try:
            parsed = json.loads(raw)
        except ValueError:
            return cls()
        if not isinstance(parsed, dict):
            return cls()
        return cls(counts={k: int(v) for k, v in parsed.items() if isinstance(v, int | float)})

    def increment(self, keys: Sequence[str]) -> RecurrenceState:
        counts = dict(self.counts)
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
        return RecurrenceState(counts=counts)

    def recurring(self, *, threshold: int = RECURRENCE_THRESHOLD) -> list[str]:
        return sorted(k for k, v in self.counts.items() if v >= threshold)


@dataclass(frozen=True, slots=True)
class InferenceResult:
    """One descriptive trait's updated recurrence state, ready to write via M04."""

    trait_key: str
    stored_value: str
    recurring: tuple[str, ...]
    model_version: str = INFERENCE_MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "trait_key": self.trait_key,
            "stored_value": self.stored_value,
            "recurring": list(self.recurring),
            "model_version": self.model_version,
        }


def _finding_rule_ids(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    """The rule_id each finding cites (M13's citation shape: {rule_id, version})."""
    rule_ids = []
    for finding in findings:
        citation = finding.get("citation")
        if isinstance(citation, Mapping) and isinstance(citation.get("rule_id"), str):
            rule_ids.append(citation["rule_id"])
    return rule_ids


def infer_weak_areas(
    *, prior_value: str | None, findings: Sequence[Mapping[str, Any]]
) -> InferenceResult:
    """Weak areas: rule_ids whose findings have recurred across sessions."""
    state = RecurrenceState.from_json(prior_value).increment(_finding_rule_ids(findings))
    return InferenceResult(
        trait_key=WEAK_AREAS_TRAIT_KEY,
        stored_value=state.to_json(),
        recurring=tuple(state.recurring()),
    )


def _within_metric_ids(benchmark_position: Sequence[Mapping[str, Any]]) -> list[str]:
    return [
        p["metric_id"]
        for p in benchmark_position
        if p.get("classification") == "within" and isinstance(p.get("metric_id"), str)
    ]


def infer_strengths(
    *, prior_value: str | None, benchmark_position: Sequence[Mapping[str, Any]]
) -> InferenceResult:
    """Strengths: metrics consistently within their benchmark range across sessions."""
    state = RecurrenceState.from_json(prior_value).increment(_within_metric_ids(benchmark_position))
    return InferenceResult(
        trait_key=STRENGTHS_TRAIT_KEY,
        stored_value=state.to_json(),
        recurring=tuple(state.recurring()),
    )
