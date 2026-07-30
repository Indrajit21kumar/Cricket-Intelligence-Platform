"""Confidence-weighted decay/EMA trait update (M16 Step 3, FR-M16-02/03, §5).

The spec's algorithm::

    new_value = decay*prior_value + (1-decay)*evidence_value      (EMA-style)
    weighting modulated by evidence_conf (low-confidence evidence moves less)

Read literally: the ``(1-decay)`` weight a fresh observation would normally
get is itself scaled by that observation's own confidence
(:data:`DECAY`, an explicit versioned constant — Ch. 8/Ch. 5 name the shape
of the update but not its numeric decay, so this is a documented choice like
every other gap this build's specs leave open). At full confidence this
reduces to plain EMA; at zero confidence the evidence contributes nothing
and the trait is untouched.

A direct, structural consequence of a fixed ``decay < 1``: no single session
can ever move a trait by more than ``(1-decay)`` of the gap toward it,
regardless of how confident that one observation was — this is exactly
FR-M16-06's outlier-resistance requirement, proven in Step 4's tests, not a
separate mechanism bolted on afterward.

The trait's stored confidence blends the same way, using the identical
weight: an established, historically well-evidenced trait's confidence is
not swept away by one shaky session either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Weight retained from the prior value at full evidence confidence. An
#: explicit, versioned engineering choice (see module docstring).
DECAY = 0.7
MODEL_VERSION = "dna-update-1.0.0"


@dataclass(frozen=True, slots=True)
class TraitUpdateResult:
    """The outcome of blending one session's evidence into a trait.

    Retains the raw ``evidence_value``/``evidence_confidence`` (not just the
    blended ``new_value``) so a persisted run log carries everything needed
    to reconstruct the evidence sequence later for a genuine replay
    (Step 6's ``recompute_traits``) — a log that only kept the blended
    output couldn't be replayed, only re-displayed.
    """

    trait_key: str
    prior_value: float | None
    new_value: float
    prior_confidence: float | None
    new_confidence: float
    evidence_value: float
    evidence_confidence: float
    model_version: str = MODEL_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "trait_key": self.trait_key,
            "prior_value": self.prior_value,
            "new_value": self.new_value,
            "prior_confidence": self.prior_confidence,
            "new_confidence": self.new_confidence,
            "evidence_value": self.evidence_value,
            "evidence_confidence": self.evidence_confidence,
            "model_version": self.model_version,
        }


def update_trait(
    *,
    trait_key: str,
    prior_value: float | None,
    prior_confidence: float | None,
    evidence_value: float,
    evidence_confidence: float,
    decay: float = DECAY,
) -> TraitUpdateResult:
    """Blend ``evidence_value`` into the trait's prior state (confidence-weighted EMA)."""
    if prior_value is None:
        # First observation ever — no history to decay from; the trait IS
        # this evidence, carrying exactly its own confidence.
        return TraitUpdateResult(
            trait_key=trait_key,
            prior_value=None,
            new_value=evidence_value,
            prior_confidence=None,
            new_confidence=evidence_confidence,
            evidence_value=evidence_value,
            evidence_confidence=evidence_confidence,
        )

    evidence_weight = (1.0 - decay) * evidence_confidence
    new_value = (1.0 - evidence_weight) * prior_value + evidence_weight * evidence_value
    new_confidence = (1.0 - evidence_weight) * (
        prior_confidence or 0.0
    ) + evidence_weight * evidence_confidence

    return TraitUpdateResult(
        trait_key=trait_key,
        prior_value=prior_value,
        new_value=new_value,
        prior_confidence=prior_confidence,
        new_confidence=new_confidence,
        evidence_value=evidence_value,
        evidence_confidence=evidence_confidence,
    )
