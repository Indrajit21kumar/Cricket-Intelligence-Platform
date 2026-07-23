"""Calibration math (M05 Step 5, FR-M05-05, NFR-M05-03; Book 4 Ch. 2 §2.3).

Pixel-to-metric scale is derived from a known reference:
- **stumps** (71.1 cm) when visible  -> method 'stump', spatial_confidence high
- else **player height** (from M04)   -> method 'height', spatial_confidence medium
- else neither                        -> method 'none',  spatial_confidence low,
                                         no scale (downstream degrades gracefully)

Every calibration carries ``spatial_confidence`` (high/medium/low). An
UNSUPPORTED camera angle caps confidence at ``low`` regardless of the
reference — positions aren't trustworthy from a bad angle. Monocular phone
video means depth (Z) is always inferred, so ``depth_estimated`` is always
True (Book 4 §2.3; widens tolerance per Book 3 Ch. 6).

Pure function, unit-testable against typical / fallback / degenerate fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Regulation stump height (cm) — the primary calibration reference (Book 4).
STUMP_HEIGHT_CM = 71.1

METHOD_STUMP = "stump"
METHOD_HEIGHT = "height"
METHOD_NONE = "none"


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    pixel_to_meter: float | None  # metres per pixel; None when uncalibrated
    spatial_confidence: str  # high | medium | low
    depth_estimated: bool  # always True for monocular video
    method: str  # stump | height | none


def _cap_low(confidence: str, angle_supported: bool) -> str:
    """An unsupported angle caps spatial_confidence at 'low'."""
    return confidence if angle_supported else "low"


def compute_calibration(
    *,
    stump_visible: bool,
    stump_pixel_height: float | None,
    player_height_cm: float | None,
    player_pixel_height: float | None,
    angle_supported: bool,
) -> CalibrationResult:
    """Derive pixel-to-metre scale + spatial_confidence (Book 4 §2.3)."""
    # Primary: stumps in frame.
    if stump_visible and stump_pixel_height and stump_pixel_height > 0:
        pixel_to_meter = (STUMP_HEIGHT_CM / 100.0) / stump_pixel_height
        return CalibrationResult(
            pixel_to_meter=pixel_to_meter,
            spatial_confidence=_cap_low("high", angle_supported),
            depth_estimated=True,
            method=METHOD_STUMP,
        )

    # Fallback: player height from M04.
    if player_height_cm and player_pixel_height and player_pixel_height > 0:
        pixel_to_meter = (player_height_cm / 100.0) / player_pixel_height
        return CalibrationResult(
            pixel_to_meter=pixel_to_meter,
            spatial_confidence=_cap_low("medium", angle_supported),
            depth_estimated=True,
            method=METHOD_HEIGHT,
        )

    # Neither reference available — uncalibrated, low confidence.
    return CalibrationResult(
        pixel_to_meter=None,
        spatial_confidence="low",
        depth_estimated=True,
        method=METHOD_NONE,
    )
