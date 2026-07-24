"""Ball output schema — the vocabulary the rest of M08 speaks (M08 §5).

M08 emits **discrete events with confidence, not a guaranteed trajectory**
(§5). The types here are built around that sentence, because the module's
whole value is being trustworthy about what it did and did not see:

- :class:`BallEvent` exists or it does not. There is no "unknown" release
  frame represented as 0 or -1 — an undetected event is simply absent from
  :class:`BallEvents`, so no consumer can accidentally read a sentinel as a
  real frame number.
- ``timing_reference`` is a first-class field with ``absolute`` as its safe
  value. M10 keys its timing model off it (AC-M08-04).
- Speed is a separate type from the events, carrying ``ESTIMATED`` provenance
  permanently — it is never a bare float that could lose its label in transit
  (NFR-M08-03, AC-M08-03).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The three events M08 detects.
EVENT_RELEASE = "release"
EVENT_BOUNCE = "bounce"
EVENT_CONTACT = "contact"

# Provenance classes (Book 4 Ch. 4). Ball positions are measured from pixels;
# speed and anything else the trajectory implies are modelled.
PROVENANCE_MEASURED = "measured"
PROVENANCE_ESTIMATED = "estimated"

# Timing reference passed to M10.
TIMING_RELEASE_RELATIVE = "release_relative"
#: The safe default. Set whenever release was not reliably detected.
TIMING_ABSOLUTE = "absolute"

# Line relative to the stumps, from the batter's point of view.
LINE_OUTSIDE_OFF = "outside_off"
LINE_OFF_STUMP = "off_stump"
LINE_MIDDLE = "middle_stump"
LINE_LEG_STUMP = "leg_stump"
LINE_DOWN_LEG = "down_leg"

# Pitching length.
LENGTH_FULL_TOSS = "full_toss"
LENGTH_YORKER = "yorker"
LENGTH_FULL = "full"
LENGTH_GOOD = "good"
LENGTH_SHORT_OF_GOOD = "short_of_good"
LENGTH_SHORT = "short"

# Run quality, matching the downstream contract.
QUALITY_OK = "ok"
QUALITY_PROVISIONAL = "provisional"
QUALITY_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BallPosition:
    """The ball in one frame, in the CIP frame (or clip-relative).

    ``streak`` marks a detection recovered from a motion smear rather than a
    round blob — it is less precisely located, and the confidence already
    reflects that, but downstream diagnostics benefit from knowing which.
    """

    frame_index: int
    x: float
    y: float
    confidence: float
    streak: bool = False
    provenance: str = PROVENANCE_MEASURED


@dataclass(frozen=True, slots=True)
class BallEvent:
    """One detected event. Its existence IS the claim that it happened."""

    kind: str  # release | bounce | contact
    frame_index: int
    confidence: float
    provenance: str = PROVENANCE_ESTIMATED


@dataclass(frozen=True, slots=True)
class SpeedEstimate:
    """Delivery speed. Always ESTIMATED — never presented as measured."""

    metres_per_second: float
    confidence: float
    #: What limited the estimate, e.g. low_fps | weak_calibration | short_track.
    limited_by: tuple[str, ...] = ()
    provenance: str = PROVENANCE_ESTIMATED

    @property
    def kph(self) -> float:
        return self.metres_per_second * 3.6


@dataclass(frozen=True, slots=True)
class BallEvents:
    """Everything M08 concluded about one delivery.

    Any of the three events may be absent. ``timing_reference`` defaults to
    ``absolute``: a run must EARN release-relative timing by detecting
    release, so the safe value is what you get by construction rather than
    something a later code path has to remember to set.
    """

    release: BallEvent | None = None
    bounce: BallEvent | None = None
    contact: BallEvent | None = None
    line: str | None = None
    line_confidence: float = 0.0
    length: str | None = None
    length_confidence: float = 0.0
    speed: SpeedEstimate | None = None
    timing_reference: str = TIMING_ABSOLUTE

    @property
    def detected(self) -> tuple[BallEvent, ...]:
        return tuple(e for e in (self.release, self.bounce, self.contact) if e is not None)

    @property
    def is_empty(self) -> bool:
        """True when nothing at all was concluded — the fail-safe outcome."""
        return not self.detected and self.speed is None and self.line is None


@dataclass(frozen=True, slots=True)
class BallCandidate:
    """One ball-like object the tracker found in a frame."""

    x: float
    y: float
    score: float
    streak: bool = False


@dataclass(frozen=True, slots=True)
class FrameCandidates:
    """Every ball-like object detected in one frame (may be empty)."""

    frame_index: int
    candidates: tuple[BallCandidate, ...] = field(default_factory=tuple)
