"""Unit tests for annotation frame selection (M07 Step 2).

Selection is pure: which frames are worth labelling. Consent is a separate
decision, enforced in test_annotation_integration.py.
"""

from __future__ import annotations

from bat_service.domain.annotation import (
    REASON_FAILED,
    REASON_LOW_CONFIDENCE,
    REASON_SAMPLED,
    dataset_checksum,
    select_frames,
)
from bat_service.domain.bat import BLADE_TIP, BatFrame, BatPart


def _frame(index: int, *, detected: bool = True, confidence: float = 0.9) -> BatFrame:
    if not detected:
        return BatFrame(frame_index=index, detected=False)
    parts = (BatPart(part=BLADE_TIP, x=1.0, y=2.0, confidence=confidence),)
    return BatFrame(frame_index=index, detected=True, parts=parts, confidence=confidence)


class TestSelection:
    def test_failed_frames_are_always_selected(self) -> None:
        frames = (_frame(0), _frame(1, detected=False), _frame(2))
        selected = select_frames(frames, sample_every=0)
        assert [s.frame_index for s in selected] == [1]
        assert selected[0].reason == REASON_FAILED
        # Nothing to learn from about a frame with no detection.
        assert selected[0].weak_label is None

    def test_low_confidence_frames_are_selected_with_a_weak_label(self) -> None:
        frames = (_frame(0, confidence=0.9), _frame(1, confidence=0.4))
        selected = select_frames(frames, sample_every=0)
        assert [s.frame_index for s in selected] == [1]
        assert selected[0].reason == REASON_LOW_CONFIDENCE
        assert selected[0].weak_label is not None
        assert selected[0].weak_label["parts"][0]["part"] == BLADE_TIP

    def test_confident_frames_are_sampled_periodically(self) -> None:
        """The corpus keeps easy cases too, or it drifts to only hard ones."""
        frames = tuple(_frame(i) for i in range(20))
        selected = select_frames(frames, sample_every=5)
        assert [s.frame_index for s in selected] == [0, 5, 10, 15]
        assert all(s.reason == REASON_SAMPLED for s in selected)

    def test_sampling_can_be_disabled(self) -> None:
        frames = tuple(_frame(i) for i in range(10))
        assert select_frames(frames, sample_every=0) == ()

    def test_boundary_confidence_is_not_low(self) -> None:
        """At the threshold exactly, the frame is treated as confident."""
        frames = (_frame(1, confidence=0.6),)
        assert select_frames(frames, low_confidence_threshold=0.6, sample_every=0) == ()


class TestChecksum:
    def test_checksum_is_order_independent(self) -> None:
        a = dataset_checksum([("clip-a", 1), ("clip-b", 2)])
        b = dataset_checksum([("clip-b", 2), ("clip-a", 1)])
        assert a == b

    def test_checksum_changes_with_content(self) -> None:
        a = dataset_checksum([("clip-a", 1)])
        b = dataset_checksum([("clip-a", 2)])
        assert a != b
