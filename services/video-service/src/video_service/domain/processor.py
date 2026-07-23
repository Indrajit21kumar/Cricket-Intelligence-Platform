"""Video preprocessing adapter + fake processor (M05 Step 3, FR-M05-03).

Preprocessing turns a raw phone clip into a normalised clip (stabilised,
frame-extracted, denoised, lighting-corrected) AND measures the signals the
rest of the pipeline reasons over: media metadata, quality signals (blur,
exposure, framing), and calibration/angle hints.

This is the "fake CV, real decision logic" seam: a real ffmpeg/OpenCV
processor plugs into :class:`VideoProcessor` later, but the angle classifier
(Step 4), calibration (Step 5), and quality gate (Step 6) are REAL code that
operate on the :class:`ClipMeasurements` envelope the processor yields — so
they are unit-testable without any video. Step 3 ships a deterministic
:class:`FakeVideoProcessor`; the dev stack has no ffmpeg/OpenCV.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ClipMeasurements:
    """Everything the pipeline needs to decide angle, calibration, and quality.

    Quality signals are normalised so the gate thresholds are stable:
    ``blur_score`` 0=sharp..1=very blurry (on the batter region), ``exposure``
    0=black..0.5=ideal..1=blown-out, ``batter_in_frame`` 0..1 fraction of the
    stroke with the batter fully framed.
    """

    width: int
    height: int
    fps: float
    frame_count: int
    duration_s: float
    blur_score: float
    exposure: float
    batter_in_frame: float
    stump_visible: bool
    stump_pixel_height: float | None
    angle_hint: str  # side_on | front_on | square | other (raw classifier hint)
    angle_confidence: float  # 0..1


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    normalized_ref: str
    measurements: ClipMeasurements


def _good_clip() -> ClipMeasurements:
    """A clean, analysable side-on clip (the fake's default)."""
    return ClipMeasurements(
        width=1920,
        height=1080,
        fps=60.0,
        frame_count=300,
        duration_s=5.0,
        blur_score=0.1,
        exposure=0.5,
        batter_in_frame=0.95,
        stump_visible=True,
        stump_pixel_height=220.0,
        angle_hint="side_on",
        angle_confidence=0.9,
    )


def normalized_key(raw_ref: str) -> str:
    """Storage key for the normalised clip, derived from the raw key."""
    if "/raw/" in raw_ref:
        return raw_ref.replace("/raw/", "/normalized/", 1)
    return f"{raw_ref}/normalized"


class VideoProcessor(Protocol):
    """Adapter every preprocessing backend (ffmpeg/OpenCV, fake) satisfies."""

    async def preprocess(self, *, raw_ref: str) -> PreprocessResult:
        """Normalise the raw clip and measure it. CPU-bound; no GPU here."""
        ...


class FakeVideoProcessor:
    """Deterministic in-process processor for dev + tests.

    Returns a clean clip by default. ``next_measurements`` lets a test inject
    a marginal/bad clip for the next call (the seam the quality-gate and
    calibration tests hang off), or ``patch`` a few fields onto the good clip.
    """

    def __init__(self) -> None:
        self.next_measurements: ClipMeasurements | None = None

    def patch(self, **fields: object) -> None:
        """Set the next clip to the good clip with these fields overridden."""
        self.next_measurements = replace(_good_clip(), **fields)  # type: ignore[arg-type]

    async def preprocess(self, *, raw_ref: str) -> PreprocessResult:
        # A real backend writes the normalised frames; the fake just returns
        # the derived key + the measurement envelope.
        measurements = self.next_measurements or _good_clip()
        self.next_measurements = None  # one-shot, like M03's fail_next
        return PreprocessResult(normalized_ref=normalized_key(raw_ref), measurements=measurements)
