"""Bat part localisation + sweet-spot derivation (M07 Step 3, FR-M07-02).

The detector gives three points: the two ends of the handle and the toe of the
blade. The sweet spot is not one of them — no detector localises it, because it
is a property of the bat's construction rather than something visible in a
frame. M07 therefore *derives* it and says so.

Where it sits: measured from the blade's shoulder (where the handle meets the
blade) toward the toe, at :data:`SWEET_SPOT_BLADE_FRACTION` of the blade
length. That is a modelled constant for a typical full-size bat, not a
measurement of this bat, so the derived point carries:

- ``provenance = derived`` (never ``measured``), and
- a confidence penalty (:data:`DERIVED_CONFIDENCE_FACTOR`) below the parts it
  was computed from — a value inferred from two estimates cannot be more
  trustworthy than either.

This is AC-M07-04 and NFR-M07-03 expressed in code rather than documentation:
downstream cannot accidentally treat the sweet spot as observed, because the
label travels with the point.
"""

from __future__ import annotations

from bat_service.domain.bat import (
    BLADE_TIP,
    HANDLE_BOTTOM,
    PROVENANCE_DERIVED,
    SWEET_SPOT,
    BatDetection,
    BatPart,
)

#: Sweet spot along the blade, measured from the shoulder toward the toe.
#: ~70% down the blade for a typical full-size bat.
SWEET_SPOT_BLADE_FRACTION = 0.70

#: Derived points are less trustworthy than the points they came from.
DERIVED_CONFIDENCE_FACTOR = 0.8


def derive_sweet_spot(detection: BatDetection) -> BatPart | None:
    """Infer the sweet-spot centre from handle_bottom -> blade_tip geometry.

    Returns None when either endpoint is missing: a sweet spot cannot be
    invented from a partial bat, and a missing point is more honest than a
    guessed one (§11 degradation policy).
    """
    shoulder = detection.part(HANDLE_BOTTOM)
    tip = detection.part(BLADE_TIP)
    if shoulder is None or tip is None:
        return None

    x = shoulder.x + (tip.x - shoulder.x) * SWEET_SPOT_BLADE_FRACTION
    y = shoulder.y + (tip.y - shoulder.y) * SWEET_SPOT_BLADE_FRACTION
    # Bounded by the weaker of the two inputs, then penalised for being derived.
    confidence = min(shoulder.confidence, tip.confidence) * DERIVED_CONFIDENCE_FACTOR
    return BatPart(
        part=SWEET_SPOT,
        x=x,
        y=y,
        confidence=confidence,
        provenance=PROVENANCE_DERIVED,
    )


def with_derived_parts(detection: BatDetection) -> BatDetection:
    """Return the detection with its derived parts appended (detected first)."""
    sweet_spot = derive_sweet_spot(detection)
    if sweet_spot is None:
        return detection
    return BatDetection(parts=(*detection.parts, sweet_spot), score=detection.score)


def detection_confidence(detection: BatDetection) -> float:
    """Per-frame detection confidence: the weakest MEASURED part.

    Deliberately the minimum over measured parts only. A mean would let a
    confidently-located handle mask a blade tip the detector never really
    found, and the blade is what every bat metric depends on. Derived parts
    are excluded so their penalty is not double-counted.
    """
    measured = [p.confidence for p in detection.parts if p.provenance != PROVENANCE_DERIVED]
    if not measured:
        return 0.0
    return min(measured)
