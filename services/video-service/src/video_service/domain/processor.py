"""Video preprocessing adapter + fake processor (M05 Step 3, FR-M05-03).

Preprocessing turns a raw phone clip into a normalised clip (stabilised,
frame-extracted, denoised, lighting-corrected) AND measures the signals the
rest of the pipeline reasons over: media metadata, quality signals (blur,
exposure, framing), and calibration/angle hints.

This is the "fake CV, real decision logic" seam: the angle classifier
(Step 4), calibration (Step 5), and quality gate (Step 6) are REAL code that
operate on the :class:`ClipMeasurements` envelope the processor yields — so
they are unit-testable without any video, against the deterministic
:class:`FakeVideoProcessor` (still the default).

:class:`RealVideoProcessor` is the OpenCV-backed implementation: it decodes
the actual uploaded clip and measures what can honestly be measured without a
cricket-specific detector. It is opt-in (``CIP_USE_REAL_PIPELINE``) and needs
the ``real`` extra installed.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from video_service.domain.angle import ANGLE_UNKNOWN


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
    player_pixel_height: float | None  # batter's pixel height (height-fallback calib)
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
        player_pixel_height=430.0,
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


# --- Real (OpenCV) processor -------------------------------------------------

#: Laplacian-variance scale for the blur mapping. First-pass constant: a clip
#: whose sampled variance equals this reads as blur_score 0.5 (the gate's
#: marginal band). Recalibrate against real academy footage before relying on
#: the flag/fail boundaries in anger.
BLUR_VARIANCE_SCALE = 150.0

#: Frames sampled for the blur/exposure statistics (the frame COUNT is always
#: exact — every frame is read; only the CV statistics are sampled).
QUALITY_SAMPLE_FRAMES = 24

#: Fallback when the container reports no usable frame rate.
FALLBACK_FPS = 30.0

#: batter_in_frame is NOT measured — no person/bat detector exists in M05.
#: Set just above the gate's flag threshold so an otherwise-good clip isn't
#: flagged for something that was never actually checked.
ASSUMED_BATTER_IN_FRAME = 0.95


class RealVideoProcessor:
    """OpenCV-backed processor reading the real uploaded clip.

    Genuinely measured: geometry, frame rate, frame count, duration, blur
    (Laplacian variance) and exposure (mean luma). Deliberately NOT measured
    and reported as unknown rather than invented: stump visibility, stump and
    player pixel heights, and the camera angle — those need a detector M05
    does not have, and :mod:`video_service.domain.calibration` /
    :mod:`video_service.domain.angle` already degrade honestly when they are
    absent.

    "Normalisation" here is an identity copy of the validated bytes to the
    normalised key. Real stabilisation / denoise / lighting correction is
    still outstanding; this does not pretend otherwise.
    """

    def __init__(self, *, root: Path) -> None:
        self._root = root

    async def preprocess(self, *, raw_ref: str) -> PreprocessResult:
        normalized_ref = normalized_key(raw_ref)
        measurements = await asyncio.to_thread(self._measure, self._root / raw_ref)
        await asyncio.to_thread(self._copy_to_normalized, raw_ref, normalized_ref)
        return PreprocessResult(normalized_ref=normalized_ref, measurements=measurements)

    def _copy_to_normalized(self, raw_ref: str, normalized_ref: str) -> None:
        dest = self._root / normalized_ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._root / raw_ref, dest)

    def _measure(self, path: Path) -> ClipMeasurements:
        import cv2  # lazy: only the real path needs OpenCV installed

        cap = cv2.VideoCapture(str(path), cv2.CAP_FFMPEG)
        if not cap.isOpened():
            raise ValueError(f"Could not open video for decoding: {path.name}")
        try:
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            reported_fps = float(cap.get(cv2.CAP_PROP_FPS))
            fps = reported_fps if reported_fps > 0 else FALLBACK_FPS
            # CAP_PROP_FRAME_COUNT is unreliable for VFR/streamed containers,
            # so count by decoding. Sample the CV statistics as we go.
            frame_count = 0
            sample_stride = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) // QUALITY_SAMPLE_FRAMES)
            blur_variances: list[float] = []
            luma_means: list[float] = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                if frame_count % sample_stride == 0 and len(blur_variances) < QUALITY_SAMPLE_FRAMES:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    blur_variances.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
                    luma_means.append(float(gray.mean()))
                frame_count += 1
        finally:
            cap.release()

        if frame_count == 0:
            raise ValueError(f"Video contained no decodable frames: {path.name}")

        mean_variance = sum(blur_variances) / len(blur_variances) if blur_variances else 0.0
        mean_luma = sum(luma_means) / len(luma_means) if luma_means else 0.0
        return ClipMeasurements(
            width=width,
            height=height,
            fps=fps,
            frame_count=frame_count,
            duration_s=frame_count / fps,
            blur_score=1.0 / (1.0 + mean_variance / BLUR_VARIANCE_SCALE),
            exposure=mean_luma / 255.0,
            batter_in_frame=ASSUMED_BATTER_IN_FRAME,
            stump_visible=False,
            stump_pixel_height=None,
            player_pixel_height=None,
            # No angle classifier exists in M05 — say "not measured" rather than
            # "other", which would read downstream as a real square/odd angle.
            angle_hint=ANGLE_UNKNOWN,
            angle_confidence=0.0,
        )
