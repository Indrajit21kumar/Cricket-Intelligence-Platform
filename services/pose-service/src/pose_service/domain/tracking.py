"""Primary-subject tracking + multi-subject rejection (M06 Step 3, AC-M06-02).

A clip may contain several people (net partner, umpire, passers-by). M06 must
follow *exactly one* batter and, when it genuinely cannot tell which person is
the batter, REJECT rather than guess (FR-M06-03) — a wrong subject would poison
every downstream metric.

Heuristic (pure, unit-testable): the batter is the largest, most central
person, tracked frame-to-frame by continuity. In a frame with 2+ people, the
pick is *unambiguous* only if the top candidate's score clearly dominates the
runner-up (``DOMINANCE_MARGIN``). If too many frames are ambiguous
(``AMBIGUITY_RATIO``), the whole clip is ``multi_subject_ambiguous``. If most
frames have no person, it is ``no_subject``.

A real deployment can swap a learned tracker behind the same signature; the
reject-don't-guess policy is the contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from pose_service.domain.keypoints import (
    SUBJECT_MULTI_AMBIGUOUS,
    SUBJECT_NONE,
    SUBJECT_TRACKED,
    FrameDetections,
    Keypoint,
    PersonDetection,
)

# A candidate is a clear winner only if its score is this many times the
# runner-up's — otherwise the frame is ambiguous.
DOMINANCE_MARGIN = 1.4
# If at least this fraction of multi-person frames are ambiguous, reject.
AMBIGUITY_RATIO = 0.3
# If fewer than this fraction of frames contain any person, it's no_subject.
MIN_PRESENCE_RATIO = 0.5


@dataclass(frozen=True, slots=True)
class TrackingResult:
    subject_status: str  # tracked | multi_subject_ambiguous | no_subject
    #: Per-frame keypoints of the chosen batter (empty unless tracked). A frame
    #: with no detection contributes an empty tuple, so indices line up 1:1
    #: with the input frames.
    frames: tuple[tuple[Keypoint, ...], ...]


def _centrality(p: PersonDetection, width: float) -> float:
    """1.0 dead-centre, →0 at the edges. Guards a zero-width frame."""
    if width <= 0:
        return 1.0
    return max(0.0, 1.0 - abs(p.cx - width / 2) / (width / 2))


def _score(p: PersonDetection, width: float) -> float:
    """Batter-likeness: bigger + more central + higher detection score."""
    return p.area * (0.5 + 0.5 * _centrality(p, width)) * max(p.score, 0.01)


def select_primary_subject(detections: list[FrameDetections], *, width: float) -> TrackingResult:
    """Pick + track one batter across the clip, or reject if ambiguous."""
    n = len(detections)
    if n == 0:
        return TrackingResult(subject_status=SUBJECT_NONE, frames=())

    present = 0
    ambiguous = 0
    multi = 0
    picks: list[tuple[Keypoint, ...]] = []

    prev_cx: float | None = None
    for fr in detections:
        people = fr.persons
        if not people:
            picks.append(())
            continue
        present += 1

        ranked = sorted(people, key=lambda p: _score(p, width), reverse=True)
        top = ranked[0]
        if len(ranked) > 1:
            multi += 1
            runner = ranked[1]
            top_s = _score(top, width)
            run_s = _score(runner, width)
            # The frame is ambiguous whenever the top candidate doesn't clearly
            # dominate the runner-up — count it toward the reject decision
            # REGARDLESS of the continuity tie-break (continuity only decides
            # WHICH of the two we'd output; it does not make the frame certain).
            if run_s > 0 and top_s < DOMINANCE_MARGIN * run_s:
                ambiguous += 1
                if prev_cx is not None:
                    anchor = prev_cx  # bind narrowed value for the closure
                    top = min(ranked[:2], key=lambda p: abs(p.cx - anchor))
        prev_cx = top.cx
        picks.append(top.keypoints)

    # No usable subject in most of the clip.
    if present < MIN_PRESENCE_RATIO * n:
        return TrackingResult(subject_status=SUBJECT_NONE, frames=())

    # Too many unresolved multi-person frames → don't guess.
    if multi > 0 and ambiguous >= AMBIGUITY_RATIO * multi:
        return TrackingResult(subject_status=SUBJECT_MULTI_AMBIGUOUS, frames=())

    return TrackingResult(subject_status=SUBJECT_TRACKED, frames=tuple(picks))
