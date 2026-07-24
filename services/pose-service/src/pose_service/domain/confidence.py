"""Confidence aggregation + provisional-output policy (M06 Step 5, AC-M06-04).

Every keypoint carries a confidence (NFR-M06-03 — no silent gap-filling). M06
aggregates per-joint → per-frame → per-clip mean, and if the clip mean is below
the confidence gate it marks the whole output ``provisional`` so the
Biomechanics Engine (M10) can widen tolerance / down-weight it rather than
treat a shaky read as solid (matches the M10 input contract, REQ-BIO-003).

Pure functions — no gap-filling, no hidden smoothing; the numbers are exactly
what the model reported.
"""

from __future__ import annotations

from dataclasses import dataclass

from pose_service.domain.keypoints import (
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    SUBJECT_TRACKED,
    Keypoint,
)

# Clip-mean confidence below this → provisional (M10 input contract).
CONFIDENCE_GATE = 0.5


@dataclass(frozen=True, slots=True)
class ConfidenceSummary:
    mean_confidence: float
    provisional: bool  # True if the clip mean is below the gate


def frame_mean(frame: tuple[Keypoint, ...]) -> float | None:
    """Mean joint confidence for one frame, or None for an empty frame."""
    if not frame:
        return None
    return sum(k.confidence for k in frame) / len(frame)


def aggregate_confidence(
    frames: tuple[tuple[Keypoint, ...], ...], *, gate: float = CONFIDENCE_GATE
) -> ConfidenceSummary:
    """Clip-mean confidence + the provisional flag (over non-empty frames)."""
    means = [m for f in frames if (m := frame_mean(f)) is not None]
    if not means:
        return ConfidenceSummary(mean_confidence=0.0, provisional=True)
    clip_mean = sum(means) / len(means)
    return ConfidenceSummary(mean_confidence=clip_mean, provisional=clip_mean < gate)


def resolve_quality(*, subject_status: str, provisional: bool) -> str:
    """Combine tracking + confidence into the pose-run quality.

    - Not tracked (multi/no subject) → ``rejected`` (nothing usable emitted).
    - Tracked but low confidence → ``provisional``.
    - Tracked + confident → ``ok``.
    """
    if subject_status != SUBJECT_TRACKED:
        return QUALITY_REJECTED
    return QUALITY_PROVISIONAL if provisional else QUALITY_OK
