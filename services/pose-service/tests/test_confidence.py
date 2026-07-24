"""Unit tests for confidence aggregation + provisional policy (M06 Step 5, AC-M06-04)."""

from __future__ import annotations

from pose_service.domain.confidence import (
    CONFIDENCE_GATE,
    aggregate_confidence,
    resolve_quality,
)
from pose_service.domain.keypoints import (
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    SUBJECT_MULTI_AMBIGUOUS,
    SUBJECT_NONE,
    SUBJECT_TRACKED,
    Keypoint,
)
from pose_service.domain.model import FakePoseModel
from pose_service.domain.tracking import select_primary_subject


def _tracked(base_confidence: float):
    model = FakePoseModel()
    model.patch(base_confidence=base_confidence)
    detections = model.infer(frame_count=8, width=1920, height=1080)
    return select_primary_subject(detections, width=1920.0).frames


class TestAggregate:
    def test_high_confidence_not_provisional(self) -> None:
        summary = aggregate_confidence(_tracked(0.9))
        assert summary.mean_confidence > CONFIDENCE_GATE
        assert summary.provisional is False

    def test_low_confidence_is_provisional(self) -> None:
        summary = aggregate_confidence(_tracked(0.3))
        assert summary.mean_confidence < CONFIDENCE_GATE
        assert summary.provisional is True

    def test_empty_frames_are_provisional_zero(self) -> None:
        summary = aggregate_confidence(((), (), ()))
        assert summary.mean_confidence == 0.0
        assert summary.provisional is True

    def test_mean_ignores_empty_frames(self) -> None:
        frame = (Keypoint(joint="nose", x=0, y=0, confidence=0.8),)
        summary = aggregate_confidence((frame, (), frame))
        assert abs(summary.mean_confidence - 0.8) < 1e-9


class TestQuality:
    def test_tracked_confident_is_ok(self) -> None:
        assert resolve_quality(subject_status=SUBJECT_TRACKED, provisional=False) == QUALITY_OK

    def test_tracked_low_confidence_is_provisional(self) -> None:
        assert (
            resolve_quality(subject_status=SUBJECT_TRACKED, provisional=True) == QUALITY_PROVISIONAL
        )

    def test_untracked_is_rejected(self) -> None:
        assert (
            resolve_quality(subject_status=SUBJECT_MULTI_AMBIGUOUS, provisional=False)
            == QUALITY_REJECTED
        )
        assert resolve_quality(subject_status=SUBJECT_NONE, provisional=True) == QUALITY_REJECTED
