"""Quality gate (M05 Step 6, FR-M05-06, NFR-M05-02, AC-M05-02).

The gate runs BEFORE any GPU stage (NFR-M05-02) and protects both accuracy
and cost: it rejects clips that can't be analysed and soft-flags marginal
ones so downstream stages degrade gracefully. A hard FAIL means the clip is
not admitted (the route returns 422 + actionable reasons); a soft FLAG lets
the clip through with reduced-confidence metadata (M05 §5.1).

Every threshold here is the SINGLE SOURCE shared with the capture-guidance
contract (Step 8, §11) — the pre-capture overlay and the post-upload gate use
the same numbers, so guidance and gate always agree.

Pure decision logic over :class:`ClipMeasurements` + the angle result, so
every check is unit-testable against typical / boundary / failure fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

from video_service.domain.angle import AngleResult
from video_service.domain.processor import ClipMeasurements

# --- Shared thresholds (gate + capture guidance) -----------------------------
MIN_WIDTH = 1280
MIN_HEIGHT = 720
FPS_FAIL_BELOW = 24.0
FPS_FLAG_BELOW = 30.0
BLUR_FAIL_ABOVE = 0.6  # blur_score 0=sharp .. 1=very blurry
BLUR_FLAG_ABOVE = 0.4
FRAMING_FAIL_BELOW = 0.7  # batter_in_frame fraction
FRAMING_FLAG_BELOW = 0.9
EXPOSURE_FAIL_LOW = 0.15  # exposure 0=black .. 0.5=ideal .. 1=blown
EXPOSURE_FAIL_HIGH = 0.85
EXPOSURE_FLAG_LOW = 0.3
EXPOSURE_FLAG_HIGH = 0.7
DURATION_MIN_S = 2.0
DURATION_MAX_S = 20.0

SEVERITY_FAIL = "fail"
SEVERITY_FLAG = "flag"


@dataclass(frozen=True, slots=True)
class GateFlag:
    code: str
    severity: str  # fail | flag
    message: str  # actionable, user-facing


@dataclass(frozen=True, slots=True)
class GateResult:
    admitted: bool  # False if ANY fail flag -> hard reject (422)
    flags: tuple[GateFlag, ...]

    @property
    def fail_reasons(self) -> list[str]:
        return [f.code for f in self.flags if f.severity == SEVERITY_FAIL]


def run_quality_gate(*, measurements: ClipMeasurements, angle: AngleResult) -> GateResult:
    """Evaluate all gate checks. Admitted iff no hard-fail flag."""
    m = measurements
    flags: list[GateFlag] = []

    # Resolution.
    if m.width < MIN_WIDTH or m.height < MIN_HEIGHT:
        flags.append(
            GateFlag(
                "resolution_too_low",
                SEVERITY_FAIL,
                f"Video resolution {m.width}x{m.height} is below the "
                f"{MIN_WIDTH}x{MIN_HEIGHT} minimum. Record in 720p or higher.",
            )
        )

    # Frame rate.
    if m.fps < FPS_FAIL_BELOW:
        flags.append(
            GateFlag(
                "frame_rate_too_low",
                SEVERITY_FAIL,
                f"Frame rate {m.fps:.0f}fps is too low to capture the stroke. "
                "Record at 30fps or higher.",
            )
        )
    elif m.fps < FPS_FLAG_BELOW:
        flags.append(
            GateFlag(
                "frame_rate_marginal",
                SEVERITY_FLAG,
                f"Frame rate {m.fps:.0f}fps is marginal — 60fps gives sharper timing.",
            )
        )

    # Motion blur / focus (on the batter region).
    if m.blur_score > BLUR_FAIL_ABOVE:
        flags.append(
            GateFlag(
                "excessive_blur",
                SEVERITY_FAIL,
                "The batter is too blurred to analyse. Steady the camera and ensure good focus.",
            )
        )
    elif m.blur_score > BLUR_FLAG_ABOVE:
        flags.append(
            GateFlag(
                "some_blur",
                SEVERITY_FLAG,
                "Some motion blur detected — a faster shutter / steadier camera helps.",
            )
        )

    # Occlusion / framing.
    if m.batter_in_frame < FRAMING_FAIL_BELOW:
        flags.append(
            GateFlag(
                "batter_not_in_frame",
                SEVERITY_FAIL,
                "The batter isn't fully in frame for the stroke. Reframe so the "
                "whole body and bat stay in shot.",
            )
        )
    elif m.batter_in_frame < FRAMING_FLAG_BELOW:
        flags.append(
            GateFlag(
                "framing_tight",
                SEVERITY_FLAG,
                "Framing is tight — leave a little more space around the batter.",
            )
        )

    # Lighting.
    if m.exposure < EXPOSURE_FAIL_LOW:
        flags.append(
            GateFlag(
                "underexposed",
                SEVERITY_FAIL,
                "The clip is too dark to analyse. Film in brighter, even lighting.",
            )
        )
    elif m.exposure > EXPOSURE_FAIL_HIGH:
        flags.append(
            GateFlag(
                "overexposed",
                SEVERITY_FAIL,
                "The clip is over-exposed. Avoid filming into strong backlight.",
            )
        )
    elif m.exposure < EXPOSURE_FLAG_LOW or m.exposure > EXPOSURE_FLAG_HIGH:
        flags.append(
            GateFlag(
                "lighting_marginal",
                SEVERITY_FLAG,
                "Lighting is uneven — more even light improves accuracy.",
            )
        )

    # Duration.
    if m.duration_s < DURATION_MIN_S or m.duration_s > DURATION_MAX_S:
        flags.append(
            GateFlag(
                "duration_out_of_range",
                SEVERITY_FAIL,
                f"Clip length {m.duration_s:.1f}s should be between "
                f"{DURATION_MIN_S:.0f}s and {DURATION_MAX_S:.0f}s and contain "
                "one complete stroke.",
            )
        )

    # Camera angle — soft flag only (proceed with low confidence, §5.1).
    if not angle.supported:
        flags.append(
            GateFlag(
                "unsupported_camera_angle",
                SEVERITY_FLAG,
                angle.recommendation or "Unsupported camera angle.",
            )
        )

    admitted = not any(f.severity == SEVERITY_FAIL for f in flags)
    return GateResult(admitted=admitted, flags=tuple(flags))


def capture_thresholds() -> dict[str, object]:
    """The thresholds the mobile capture overlay enforces (Step 8, §11).

    The same numbers the gate uses — so pre-capture guidance and the
    post-upload gate never disagree.
    """
    return {
        "min_width": MIN_WIDTH,
        "min_height": MIN_HEIGHT,
        "min_fps": FPS_FLAG_BELOW,
        "max_blur_score": BLUR_FLAG_ABOVE,
        "min_batter_in_frame": FRAMING_FLAG_BELOW,
        "exposure_ok_range": [EXPOSURE_FLAG_LOW, EXPOSURE_FLAG_HIGH],
        "duration_range_s": [DURATION_MIN_S, DURATION_MAX_S],
        "supported_angles": ["side_on", "front_on"],
    }
