"""Shot output schema — the vocabulary the rest of M09 speaks (M09 §5).

The v1 taxonomy plus phase definitions. Two ideas from the spec are pushed into
the types so they cannot be forgotten downstream:

- **Abstention is a value, not an absence.** :data:`UNCLASSIFIED` is a real
  member of the class set, not ``None``. A low-confidence stroke is positively
  labelled unclassified so M10 applies generic handling rather than tripping
  over a missing field (FR-M09-02).
- **Phase method is explicit.** :class:`PhaseBoundaries` carries how it was
  derived — ball-anchored ``standard`` or ``bat_only_fallback`` — because M10
  trusts a ball-anchored impact frame differently from a bat-inferred one
  (AC-M09-04).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

# --- shot taxonomy (v1 set, Book 4 Ch. 5; extensible via CIP-STD) -------------
STRAIGHT_DRIVE = "straight_drive"
COVER_DRIVE = "cover_drive"
ON_DRIVE = "on_drive"
FLICK = "flick"
PULL = "pull"
HOOK = "hook"
CUT = "cut"
SWEEP = "sweep"
REVERSE_SWEEP = "reverse_sweep"
LOFTED = "lofted_shot"
DEFENSIVE = "defensive_stroke"

#: The positive outcome of abstention — never None.
UNCLASSIFIED = "unclassified"

SHOT_CLASSES: tuple[str, ...] = (
    STRAIGHT_DRIVE,
    COVER_DRIVE,
    ON_DRIVE,
    FLICK,
    PULL,
    HOOK,
    CUT,
    SWEEP,
    REVERSE_SWEEP,
    LOFTED,
    DEFENSIVE,
)

# --- phases (biomechanics phase model, REQ-BIO-007) ---------------------------
PHASE_STANCE = "stance"
PHASE_BACKLIFT = "backlift"
PHASE_DOWNSWING = "downswing"
PHASE_IMPACT = "impact"
PHASE_FOLLOW_THROUGH = "follow_through"

#: Order matters: boundaries must be monotonic in this sequence.
PHASE_ORDER: tuple[str, ...] = (
    PHASE_STANCE,
    PHASE_BACKLIFT,
    PHASE_DOWNSWING,
    PHASE_IMPACT,
    PHASE_FOLLOW_THROUGH,
)

# How the phases were segmented.
METHOD_STANDARD = "standard"
METHOD_BAT_ONLY_FALLBACK = "bat_only_fallback"

# Which upstream signals were available to the classifier.
SIGNAL_POSE = "pose"
SIGNAL_BAT = "bat"
SIGNAL_BALL = "ball"

# Run quality.
QUALITY_OK = "ok"
QUALITY_PROVISIONAL = "provisional"
QUALITY_UNCLASSIFIED = "unclassified"


@dataclass(frozen=True, slots=True)
class ClassScore:
    """One class and the model's score for it."""

    shot_class: str
    score: float


@dataclass(frozen=True, slots=True)
class Classification:
    """The classifier's verdict, before abstention is applied."""

    shot_class: str
    confidence: float
    #: Full ranked distribution, so abstention can inspect the top-2 margin.
    scores: tuple[ClassScore, ...] = ()

    @property
    def runner_up_margin(self) -> float:
        """Gap between the top class and the next. Small = ambiguous."""
        if len(self.scores) < 2:
            return 1.0
        ranked = sorted(self.scores, key=lambda s: s.score, reverse=True)
        return ranked[0].score - ranked[1].score


@dataclass(frozen=True, slots=True)
class PhaseBoundaries:
    """Frame indices for the five phases, plus how they were derived.

    Each field is the START frame of that phase. ``follow_through`` runs to the
    end of the clip. Boundaries are monotonic non-decreasing in PHASE_ORDER.
    """

    stance: int
    backlift: int
    downswing: int
    impact: int
    follow_through: int
    method: str

    def as_dict(self) -> dict[str, int]:
        return {
            PHASE_STANCE: self.stance,
            PHASE_BACKLIFT: self.backlift,
            PHASE_DOWNSWING: self.downswing,
            PHASE_IMPACT: self.impact,
            PHASE_FOLLOW_THROUGH: self.follow_through,
        }

    @property
    def is_monotonic(self) -> bool:
        seq = (self.stance, self.backlift, self.downswing, self.impact, self.follow_through)
        return all(a <= b for a, b in itertools.pairwise(seq))


@dataclass(frozen=True, slots=True)
class ShotResult:
    """Everything M09 concluded about one stroke."""

    shot_class: str
    shot_confidence: float
    phases: PhaseBoundaries
    signals_used: tuple[str, ...]
    quality: str
    #: Present when the top class was abstained on — kept for the annotation
    #: flywheel, since a near-miss is a good thing to label.
    abstained_from: str | None = None
    scores: tuple[ClassScore, ...] = field(default_factory=tuple)

    @property
    def abstained(self) -> bool:
        return self.shot_class == UNCLASSIFIED
