"""Trait-update sequence replay (M16 Step 4, FR-M16-06/08, NFR-M16-04).

Applies a sequence of evidence to a trait, one update at a time, retaining
EVERY intermediate result — the same append-only guarantee M04's
``dna_trait_history`` table enforces at the storage layer, proven here at
the computation layer: replaying N pieces of evidence always yields exactly
N results, each chained to the previous (its ``prior_value``/
``prior_confidence`` match the previous result's ``new_value``/
``new_confidence`` exactly), so no update is ever silently skipped or
overwritten.

This is also the primitive Step 6's deterministic recompute/replay uses:
recomputing a trait from its full evidence history is just calling this
function with that trait's whole history, from scratch (NFR-M16-02).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dna_service.domain.decay import DECAY, TraitUpdateResult, update_trait


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    """One session's evidence for a trait, ready to replay."""

    value: float
    confidence: float
    source_ref: str


def replay_sequence(
    trait_key: str, evidence: Sequence[EvidencePoint], *, decay: float = DECAY
) -> list[TraitUpdateResult]:
    """Apply ``evidence`` in order, retaining every intermediate result."""
    history: list[TraitUpdateResult] = []
    prior_value: float | None = None
    prior_confidence: float | None = None
    for point in evidence:
        result = update_trait(
            trait_key=trait_key,
            prior_value=prior_value,
            prior_confidence=prior_confidence,
            evidence_value=point.value,
            evidence_confidence=point.confidence,
            decay=decay,
        )
        history.append(result)
        prior_value = result.new_value
        prior_confidence = result.new_confidence
    return history
