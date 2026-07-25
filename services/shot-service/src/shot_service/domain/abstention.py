"""Calibrated abstention (M09 Step 3, FR-M09-02, AC-M09-02).

The rule the whole module turns on: a likely-wrong shot label is worse than no
label. A wrong class sends M10 to the wrong benchmark ranges (a cover drive
judged against pull-shot norms), so M09 abstains — emits ``unclassified`` — and
M10 applies generic handling instead (§11).

Abstention fires on TWO conditions, because "confident" means two things and a
classifier can fail either:

1. **Low top confidence.** The best class is simply not likely enough
   (:data:`MIN_CONFIDENCE`). Straightforward.
2. **Ambiguous top-2.** The best and second-best are nearly tied
   (:data:`MIN_MARGIN`). A cover drive at 0.42 and an on drive at 0.40 is not
   0.42 confidence in a cover drive — it is a coin toss the top-line number
   hides. This is the case a naive threshold misses, and the reason the
   classifier returns a full distribution rather than just a winner.

When it abstains, M09 keeps what it would have said (``abstained_from``) and
the full distribution, because a near-miss is precisely the sample worth
sending to a human labeller (the Step 5 flywheel).
"""

from __future__ import annotations

from shot_service.domain.shot import (
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_UNCLASSIFIED,
    UNCLASSIFIED,
    Classification,
    PhaseBoundaries,
    ShotResult,
)

#: The top class must be at least this likely to be emitted.
MIN_CONFIDENCE = 0.45

#: The top class must beat the runner-up by at least this, or the two are
#: too close to call and M09 abstains.
MIN_MARGIN = 0.10

#: Above the floor but below this, the class is emitted yet flagged provisional
#: — good enough to use, not good enough to trust silently.
PROVISIONAL_CONFIDENCE = 0.65


def resolve(
    classification: Classification,
    *,
    phases: PhaseBoundaries,
    signals_used: tuple[str, ...],
) -> ShotResult:
    """Apply the abstention policy and assemble the final shot result."""
    low_confidence = classification.confidence < MIN_CONFIDENCE
    ambiguous = classification.runner_up_margin < MIN_MARGIN

    if low_confidence or ambiguous:
        return ShotResult(
            shot_class=UNCLASSIFIED,
            shot_confidence=classification.confidence,
            phases=phases,
            signals_used=signals_used,
            quality=QUALITY_UNCLASSIFIED,
            # Keep the near-miss — it is the best thing to label (Step 5).
            abstained_from=classification.shot_class or None,
            scores=classification.scores,
        )

    quality = (
        QUALITY_OK if classification.confidence >= PROVISIONAL_CONFIDENCE else QUALITY_PROVISIONAL
    )
    return ShotResult(
        shot_class=classification.shot_class,
        shot_confidence=classification.confidence,
        phases=phases,
        signals_used=signals_used,
        quality=quality,
        scores=classification.scores,
    )
