"""Which ball frames are worth a human's time (M08 Step 7, FR-M08-09).

Selection only — the queue, the consent gate and the dataset freeze live in
``cip-annotation``, shared with M07.

M08 selects differently from M07, which is exactly why selection stays per
module. The most valuable ball frames to label are the ones the tracker could
NOT use: a delivery that failed the fail-safe is a labelled example of the hard
case that made it fail, and hard cases are what a ball detector is short of.
So a suppressed run contributes MORE to the corpus than a clean one, not less —
provided the player consented, which ``cip-annotation`` enforces regardless of
anything decided here.
"""

from __future__ import annotations

from typing import Any

from ball_service.domain.pipeline import BallRunResult
from cip_annotation import (
    REASON_FAILED,
    REASON_LOW_CONFIDENCE,
    REASON_SAMPLED,
    SelectedFrame,
)

#: Positions the tracker was unsure about are worth a labeller's attention.
LOW_CONFIDENCE_THRESHOLD = 0.6
#: Sample every Nth confident frame so the corpus keeps easy cases too.
SAMPLE_EVERY = 8
#: Cap on frames queued from a single suppressed delivery, so one bad clip
#: cannot flood the queue.
MAX_FAILED_FRAMES = 12


def select_frames(result: BallRunResult) -> tuple[SelectedFrame, ...]:
    """Choose which frames of this delivery are worth labelling."""
    # A delivery M08 could not track is the most informative thing it can
    # contribute: a labelled hard case. Sample across the clip rather than
    # taking a burst from one moment.
    if result.failsafe.suppressed:
        total = max(result.frame_count, 1)
        stride = max(total // MAX_FAILED_FRAMES, 1)
        return tuple(
            SelectedFrame(frame_index=i, reason=REASON_FAILED) for i in range(0, total, stride)
        )

    selected: list[SelectedFrame] = []
    for position in result.track.positions:
        weak_label: dict[str, Any] = {
            "x": position.x,
            "y": position.y,
            "confidence": position.confidence,
            "streak": position.streak,
        }
        if position.confidence < LOW_CONFIDENCE_THRESHOLD or position.streak:
            selected.append(
                SelectedFrame(
                    frame_index=position.frame_index,
                    reason=REASON_LOW_CONFIDENCE,
                    weak_label=weak_label,
                )
            )
        elif SAMPLE_EVERY > 0 and position.frame_index % SAMPLE_EVERY == 0:
            selected.append(
                SelectedFrame(
                    frame_index=position.frame_index,
                    reason=REASON_SAMPLED,
                    weak_label=weak_label,
                )
            )
    return tuple(selected)
