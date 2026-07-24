"""Bat output schema — the vocabulary the rest of M07 speaks (M07 §5).

Two ideas carry the module's honesty requirement into the type system:

- **Parts are detected; the sweet spot is not.** ``handle_top``,
  ``handle_bottom`` and ``blade_tip`` come from the detector. The sweet spot
  is inferred from blade geometry, so it is marked ``derived`` and never
  presented at the same confidence (NFR-M07-03, AC-M07-04).
- **A frame may legitimately have no bat.** Motion blur through the backlift
  and occlusion by the body are expected failure modes (§11), so
  :class:`BatFrame` models "not detected" explicitly rather than leaning on
  an empty parts tuple that a caller might read as zeroes.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Detected parts, in handle-to-toe order.
HANDLE_TOP = "handle_top"
HANDLE_BOTTOM = "handle_bottom"
BLADE_TIP = "blade_tip"
SWEET_SPOT = "sweet_spot"

#: What the detector localises directly.
DETECTED_PARTS: tuple[str, ...] = (HANDLE_TOP, HANDLE_BOTTOM, BLADE_TIP)
#: Everything M07 emits per frame, detected + derived.
CANONICAL_PARTS: tuple[str, ...] = (*DETECTED_PARTS, SWEET_SPOT)

# Provenance labels (Book 4 trust doctrine).
PROVENANCE_MEASURED = "measured"
PROVENANCE_DERIVED = "derived"

# Run quality, matching the M10 input contract.
QUALITY_OK = "ok"
QUALITY_PROVISIONAL = "provisional"
QUALITY_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class BatPart:
    """One localised point on the bat, in pixel space until normalisation."""

    part: str
    x: float
    y: float
    confidence: float
    #: measured (detector output) or derived (inferred from other parts).
    provenance: str = PROVENANCE_MEASURED


@dataclass(frozen=True, slots=True)
class BatDetection:
    """One bat-like object the detector found in a frame."""

    parts: tuple[BatPart, ...]
    #: Whole-object detection score, distinct from per-part confidence.
    score: float

    def part(self, name: str) -> BatPart | None:
        for p in self.parts:
            if p.part == name:
                return p
        return None


@dataclass(frozen=True, slots=True)
class FrameDetections:
    """Every bat-like object detected in one frame (may be empty)."""

    frame_index: int
    bats: tuple[BatDetection, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class BatFrame:
    """The tracked bat in one frame of the final output.

    ``detected=False`` means the bat was genuinely not found in this frame —
    the parts tuple is empty and downstream must not interpolate silently.
    """

    frame_index: int
    detected: bool
    parts: tuple[BatPart, ...] = field(default_factory=tuple)
    confidence: float = 0.0

    def part(self, name: str) -> BatPart | None:
        for p in self.parts:
            if p.part == name:
                return p
        return None
