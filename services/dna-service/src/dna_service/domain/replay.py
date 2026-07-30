"""Idempotency + deterministic recompute (M16 Step 6, FR-M16-08, NFR-M16-02/03).

Two guarantees this step proves, both already implied by earlier steps'
pure functions but not yet demonstrated end to end:

- **Determinism / recompute** (NFR-M16-02, AC-M16-05): replaying the SAME
  evidence sequence always reproduces the SAME final trait state, and —
  critically — applying evidence one session at a time (the normal
  incremental path) produces EXACTLY the same result as replaying the whole
  history from scratch in one call (the backfill/repair path, FR-M16-08).
  Because :func:`~dna_service.domain.decay.update_trait` and
  :func:`~dna_service.domain.history.replay_sequence` are pure functions of
  their inputs (no randomness, no wall-clock, no hidden state), this holds
  by construction — :func:`recompute_traits` makes it a multi-trait
  operation, the primitive Step 7's ``POST /internal/v1/dna/recompute``
  calls.
- **Idempotency** (NFR-M16-03, AC-M16-06): a session already recorded in
  ``dna_update_runs`` (keyed on ``(player_id, session_ref)``, Step 1) must
  not be applied a second time. :func:`already_processed` is the pure
  decision function Step 7's service layer checks before doing any work.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from dna_service.domain.decay import DECAY, TraitUpdateResult
from dna_service.domain.history import EvidencePoint, replay_sequence


def recompute_traits(
    evidence_by_trait: Mapping[str, Sequence[EvidencePoint]], *, decay: float = DECAY
) -> dict[str, TraitUpdateResult | None]:
    """Recompute every trait's current state from its full evidence history.

    The backfill/repair primitive (FR-M16-08): pass every session's evidence
    for a player, keyed by trait_key, and get back exactly the same current
    state the normal incremental path would have produced. A trait with no
    evidence at all recomputes to None (never seen, not a fabricated value).
    """
    result: dict[str, TraitUpdateResult | None] = {}
    for trait_key, evidence in evidence_by_trait.items():
        history = replay_sequence(trait_key, evidence, decay=decay)
        result[trait_key] = history[-1] if history else None
    return result


def already_processed(processed_session_refs: Sequence[str], session_ref: str) -> bool:
    """Whether ``session_ref`` has already been applied for this player (NFR-M16-03)."""
    return session_ref in processed_session_refs
