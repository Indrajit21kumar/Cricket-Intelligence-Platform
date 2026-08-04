"""Unit tests for the full pose compute pipeline (M06 Steps 2-5, AC-M06-01..04)."""

from __future__ import annotations

from collections.abc import Sequence

from pose_service.domain.keypoints import (
    CANONICAL_JOINTS,
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_REJECTED,
    SUBJECT_MULTI_AMBIGUOUS,
    SUBJECT_TRACKED,
    FrameImage,
)
from pose_service.domain.model import MODEL_VERSION, FakePoseModel
from pose_service.domain.pipeline import compute_pose_run


class TestHappyPath:
    def test_good_clip_tracked_ok(self) -> None:
        result = compute_pose_run(FakePoseModel(), frame_count=20, width=1920, height=1080)
        assert result.subject_status == SUBJECT_TRACKED
        assert result.quality == QUALITY_OK
        assert result.model_version == MODEL_VERSION
        assert result.frame_count == 20
        assert len(result.frames) == 20
        # Per-frame keypoints are the full canonical set, in the CIP frame.
        assert [k.joint for k in result.frames[0]] == list(CANONICAL_JOINTS)
        assert result.mean_confidence > 0.5
        # Monocular by default — the capture decides this, not the pose stage.
        assert result.depth_estimated is True

    def test_depth_flag_is_carried_from_the_capture(self) -> None:
        """A true multi-camera capture is not relabelled as estimated."""
        result = compute_pose_run(
            FakePoseModel(), frame_count=8, width=1920, height=1080, depth_estimated=False
        )
        assert result.depth_estimated is False


class TestProvisional:
    def test_low_confidence_clip_is_provisional_but_emitted(self) -> None:
        model = FakePoseModel()
        model.patch(base_confidence=0.3)
        result = compute_pose_run(model, frame_count=12, width=1920, height=1080)
        assert result.subject_status == SUBJECT_TRACKED
        assert result.quality == QUALITY_PROVISIONAL  # AC-M06-04
        assert len(result.frames) == 12  # still emitted, just flagged


class TestRejected:
    def test_ambiguous_multi_subject_rejected_no_frames(self) -> None:
        # Manually feed two comparable people so tracking rejects.
        from pose_service.domain.keypoints import FrameDetections, Keypoint, PersonDetection

        def person(cx: float) -> PersonDetection:
            kps = tuple(Keypoint(joint=j, x=cx, y=500, confidence=0.9) for j in CANONICAL_JOINTS)
            return PersonDetection(keypoints=kps, score=0.9, cx=cx, cy=500, area=1_000_000)

        class TwoEqualModel:
            version = MODEL_VERSION

            def infer(
                self,
                *,
                frame_count: int,
                width: int,
                height: int,
                frames: Sequence[FrameImage] | None = None,
            ) -> list[FrameDetections]:
                a, b = person(width * 0.45), person(width * 0.55)
                return [FrameDetections(frame_index=i, persons=(a, b)) for i in range(frame_count)]

        result = compute_pose_run(TwoEqualModel(), frame_count=10, width=1920, height=1080)
        assert result.subject_status == SUBJECT_MULTI_AMBIGUOUS
        assert result.quality == QUALITY_REJECTED
        assert result.frames == ()
        assert result.mean_confidence == 0.0
