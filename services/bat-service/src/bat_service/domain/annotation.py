"""Which bat frames are worth a human's time (M07 Step 2, FR-M07-08).

Selection only. The queue itself, the consent gate that guards it and the
dataset freeze all live in ``cip-annotation``, shared with M08 — the flywheel
is platform-wide and the consent rule must exist in one audited place.

Selection stays here because it is genuinely module-specific: M07 wants the bat
frames a detector was unsure about, M08 wants deliveries. Keeping the two apart
is also the safety property — "which frames are useful" must never drift into
"which frames are allowed".
"""

from __future__ import annotations

from typing import Any

from bat_service.domain.bat import BatFrame
from cip_annotation import (
    REASON_FAILED,
    REASON_LOW_CONFIDENCE,
    REASON_SAMPLED,
    SelectedFrame,
)

#: Frames the detector was unsure about are the most informative to label.
LOW_CONFIDENCE_THRESHOLD = 0.6
#: Take every Nth confident frame too, so the corpus keeps easy cases and does
#: not drift into being only hard ones.
SAMPLE_EVERY = 10


def select_frames(
    frames: tuple[BatFrame, ...],
    *,
    low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD,
    sample_every: int = SAMPLE_EVERY,
) -> tuple[SelectedFrame, ...]:
    """Choose which bat frames are worth labelling. No consent logic here."""
    selected: list[SelectedFrame] = []
    for frame in frames:
        if not frame.detected:
            selected.append(SelectedFrame(frame_index=frame.frame_index, reason=REASON_FAILED))
            continue
        weak_label: dict[str, Any] = {
            "parts": [
                {"part": p.part, "x": p.x, "y": p.y, "confidence": p.confidence}
                for p in frame.parts
            ]
        }
        if frame.confidence < low_confidence_threshold:
            selected.append(
                SelectedFrame(
                    frame_index=frame.frame_index,
                    reason=REASON_LOW_CONFIDENCE,
                    weak_label=weak_label,
                )
            )
        elif sample_every > 0 and frame.frame_index % sample_every == 0:
            selected.append(
                SelectedFrame(
                    frame_index=frame.frame_index,
                    reason=REASON_SAMPLED,
                    weak_label=weak_label,
                )
            )
    return tuple(selected)
