"""Phase alignment against M09's boundaries (M10 Step 3, FR-M10-03).

Every phase-relative BM metric - backlift peak, downswing bat path, impact
frame, follow-through end - needs the right frame window, and those windows
come from M09, not from M10 re-deriving them. This module turns M09's five
boundary frames into windows the formulas slice against, and carries the
``phase_method`` through so the report records whether the timing rests on ball
events (``standard``) or the bat-only fallback.

The one judgement here is what to do with degenerate boundaries. M09 can emit a
collapsed segmentation (all boundaries equal) for a stroke it could barely see.
Rather than let a formula index an empty or inverted window, the aligner clamps
each window to a valid, non-decreasing frame range within the clip and reports
whether the phases were usable - so a degenerate stroke produces empty windows
the formulas skip, not a crash or a nonsense number.
"""

from __future__ import annotations

from dataclasses import dataclass

from biomechanics_service.domain.stroke import Phases


@dataclass(frozen=True, slots=True)
class PhaseWindow:
    """Inclusive frame range [start, end] for one phase."""

    name: str
    start: int
    end: int

    @property
    def is_empty(self) -> bool:
        return self.end < self.start

    def contains(self, frame_index: int) -> bool:
        return self.start <= frame_index <= self.end


@dataclass(frozen=True, slots=True)
class AlignedPhases:
    """Phase windows + the impact frame + the segmentation method."""

    stance: PhaseWindow
    backlift: PhaseWindow
    downswing: PhaseWindow
    follow_through: PhaseWindow
    impact_frame: int
    method: str

    @property
    def usable(self) -> bool:
        """True when at least the downswing spans a real range.

        The downswing is where the bat-dependent metrics live; if it collapsed,
        the stroke was not really seen and phase-relative work should be skipped.
        """
        return not self.downswing.is_empty


def align_phases(phases: Phases, *, frame_count: int) -> AlignedPhases:
    """Turn M09 boundaries into clamped, ordered windows.

    Each phase runs from its own boundary frame up to (but not into) the next.
    Follow-through runs to the last frame. Boundaries are clamped monotonic and
    in-range so a collapsed M09 segmentation yields empty windows, never an
    inverted one.
    """
    last = max(frame_count - 1, 0)

    # Clamp the five boundaries monotonic and in-range.
    b = [phases.stance, phases.backlift, phases.downswing, phases.impact, phases.follow_through]
    clamped: list[int] = []
    current = 0
    for value in b:
        current = max(current, min(max(value, 0), last))
        clamped.append(current)
    stance_s, backlift_s, downswing_s, impact_s, follow_s = clamped

    return AlignedPhases(
        # A phase ends the frame before the next phase starts; empty when they
        # coincide (collapsed segmentation).
        stance=PhaseWindow("stance", stance_s, backlift_s - 1),
        backlift=PhaseWindow("backlift", backlift_s, downswing_s - 1),
        downswing=PhaseWindow("downswing", downswing_s, impact_s - 1),
        follow_through=PhaseWindow("follow_through", impact_s, follow_s),
        impact_frame=impact_s,
        method=phases.method,
    )
