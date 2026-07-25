"""Which strokes are worth a human's time (M09 Step 5, FR-M09-08).

Selection only — the queue, the consent gate and the dataset freeze live in
``cip-annotation``, shared with M07/M08.

M09's most valuable samples are the ones it got WRONG or could not call: an
abstention is a near-miss a human can resolve, and a low-confidence call is one
worth confirming. Confident classifications are cheap and add little, so they
are sampled sparingly. A shot is a whole-stroke label, so M09 queues one item
per stroke (frame_index 0, spanning the clip) rather than per frame — the
labeller assigns a class, not a per-frame geometry.
"""

from __future__ import annotations

from cip_annotation import (
    REASON_ABSTAINED,
    REASON_LOW_CONFIDENCE,
    SelectedFrame,
)
from shot_service.domain.pipeline import ShotRunResult

#: A classification below this is worth a human's confirmation.
LOW_CONFIDENCE_THRESHOLD = 0.65


def select_frames(run: ShotRunResult) -> tuple[SelectedFrame, ...]:
    """Choose whether this stroke is worth labelling.

    Returns at most one item: a shot label covers the whole stroke, so there is
    nothing per-frame to select. The weak label carries what the model thought,
    including the near-miss it abstained from, so the labeller starts from the
    model's best guess rather than a blank.
    """
    result = run.result
    if result.abstained:
        return (
            SelectedFrame(
                frame_index=0,
                reason=REASON_ABSTAINED,
                weak_label={
                    "abstained_from": result.abstained_from,
                    "confidence": result.shot_confidence,
                    "signals": list(result.signals_used),
                },
            ),
        )
    if result.shot_confidence < LOW_CONFIDENCE_THRESHOLD:
        return (
            SelectedFrame(
                frame_index=0,
                reason=REASON_LOW_CONFIDENCE,
                weak_label={
                    "shot_class": result.shot_class,
                    "confidence": result.shot_confidence,
                    "signals": list(result.signals_used),
                },
            ),
        )
    return ()
