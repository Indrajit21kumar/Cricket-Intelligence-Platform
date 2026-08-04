"""Camera-angle classification (M05 Step 4, FR-M05-04).

Real decision logic over the processor's raw angle hint + confidence. Cricket
batting analysis is calibrated for **side-on** (primary) and **front-on**
views; **square** and **other** are unsupported. An unsupported or
low-confidence angle isn't a hard fail — the clip proceeds with
``spatial_confidence: low`` plus a re-film recommendation (M05 §5.1). The
quality gate (Step 6) turns that into a soft flag.

Pure function, so it is unit-testable against typical / boundary fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

ALL_ANGLES = ("side_on", "front_on", "square", "other")
#: Angles the biomechanics pipeline can analyse with full spatial confidence.
SUPPORTED_ANGLES = frozenset({"side_on", "front_on"})
#: Below this the classifier isn't sure enough to trust the angle.
DEFAULT_MIN_CONFIDENCE = 0.5
#: Sentinel hint meaning "no angle classifier ran" — distinct from a classifier
#: that ran and was unsure. A processor with no angle detector reports this, so
#: the gate can say "not assessed yet" instead of telling the person to re-film
#: because of a measurement that was never actually taken.
ANGLE_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AngleResult:
    camera_angle: str  # canonical: side_on | front_on | square | other
    supported: bool  # analysable at full confidence?
    confidence: float
    recommendation: str | None  # re-film guidance when not supported
    #: False when no classifier ran at all (see :data:`ANGLE_UNKNOWN`).
    assessed: bool = True


def classify_angle(
    *, angle_hint: str, angle_confidence: float, min_confidence: float = DEFAULT_MIN_CONFIDENCE
) -> AngleResult:
    """Classify the viewing angle and decide whether it is analysable."""
    # No classifier ran: report honestly rather than blaming the camera angle.
    if angle_hint == ANGLE_UNKNOWN:
        return AngleResult(
            camera_angle="other",
            supported=False,
            confidence=0.0,
            recommendation=(
                "Camera angle isn't analysed yet. Filming side-on (from square-leg "
                "or point) will give the best results as angle-aware analysis lands."
            ),
            assessed=False,
        )

    angle = angle_hint if angle_hint in ALL_ANGLES else "other"
    low_confidence = angle_confidence < min_confidence
    supported = angle in SUPPORTED_ANGLES and not low_confidence

    recommendation: str | None = None
    if not supported:
        if low_confidence:
            recommendation = (
                "Camera angle unclear — set the phone side-on to the batter, "
                "steady on a tripod, with the whole stroke in frame."
            )
        elif angle == "square":
            recommendation = (
                "Square-on angle detected — move to a side-on position "
                "(square-leg or point) for accurate analysis."
            )
        else:
            recommendation = (
                "Unsupported camera angle — film from a side-on position with the stumps in frame."
            )

    return AngleResult(
        camera_angle=angle,
        supported=supported,
        confidence=angle_confidence,
        recommendation=recommendation,
    )
