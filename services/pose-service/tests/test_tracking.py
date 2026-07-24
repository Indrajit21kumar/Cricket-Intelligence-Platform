"""Unit tests for primary-subject tracking (M06 Step 3, AC-M06-02).

Pure logic — no DB/Kafka. Single batter tracked; multiple comparable people
rejected as ambiguous rather than guessed; empty clip = no_subject.
"""

from __future__ import annotations

from pose_service.domain.keypoints import (
    CANONICAL_JOINTS,
    SUBJECT_MULTI_AMBIGUOUS,
    SUBJECT_NONE,
    SUBJECT_TRACKED,
    FrameDetections,
    Keypoint,
    PersonDetection,
)
from pose_service.domain.model import FakePoseModel
from pose_service.domain.tracking import select_primary_subject

WIDTH = 1920.0
HEIGHT = 1080.0


def _person(*, cx: float, area: float, score: float = 0.9) -> PersonDetection:
    kps = tuple(Keypoint(joint=j, x=cx, y=HEIGHT / 2, confidence=score) for j in CANONICAL_JOINTS)
    return PersonDetection(keypoints=kps, score=score, cx=cx, cy=HEIGHT / 2, area=area)


def _frames(persons_per_frame: list[list[PersonDetection]]) -> list[FrameDetections]:
    return [
        FrameDetections(frame_index=i, persons=tuple(ps)) for i, ps in enumerate(persons_per_frame)
    ]


class TestTracked:
    def test_single_batter_tracked(self) -> None:
        model = FakePoseModel()
        detections = model.infer(frame_count=12, width=1920, height=1080)
        result = select_primary_subject(detections, width=WIDTH)
        assert result.subject_status == SUBJECT_TRACKED
        assert len(result.frames) == 12
        assert all(len(f) == len(CANONICAL_JOINTS) for f in result.frames)

    def test_dominant_person_wins_over_bystander(self) -> None:
        # A big central batter + a small person off to the side, every frame.
        big = _person(cx=WIDTH / 2, area=(0.42 * HEIGHT) ** 2)
        small = _person(cx=WIDTH * 0.12, area=(0.20 * HEIGHT) ** 2)
        result = select_primary_subject(_frames([[big, small]] * 10), width=WIDTH)
        assert result.subject_status == SUBJECT_TRACKED
        # The tracked keypoints are the big central person's (cx == centre).
        assert result.frames[0][0].x == WIDTH / 2


class TestMultiSubjectRejected:
    def test_two_comparable_people_are_ambiguous(self) -> None:
        # Two similarly sized, similarly central people -> cannot tell -> reject.
        a = _person(cx=WIDTH * 0.45, area=(0.40 * HEIGHT) ** 2)
        b = _person(cx=WIDTH * 0.55, area=(0.40 * HEIGHT) ** 2)
        result = select_primary_subject(_frames([[a, b]] * 10), width=WIDTH)
        assert result.subject_status == SUBJECT_MULTI_AMBIGUOUS
        assert result.frames == ()  # not guessed

    def test_model_patched_to_two_subjects_still_resolves_when_dominant(self) -> None:
        # The fake's extra person is smaller/side -> still resolvable, not rejected.
        model = FakePoseModel()
        model.patch(persons=2)
        detections = model.infer(frame_count=8, width=1920, height=1080)
        result = select_primary_subject(detections, width=WIDTH)
        assert result.subject_status == SUBJECT_TRACKED


class TestNoSubject:
    def test_empty_clip_is_no_subject(self) -> None:
        result = select_primary_subject([], width=WIDTH)
        assert result.subject_status == SUBJECT_NONE

    def test_mostly_empty_frames_is_no_subject(self) -> None:
        big = _person(cx=WIDTH / 2, area=(0.4 * HEIGHT) ** 2)
        # 8 empty frames, 2 with a person -> below MIN_PRESENCE_RATIO.
        frames = _frames([[]] * 8 + [[big]] * 2)
        result = select_primary_subject(frames, width=WIDTH)
        assert result.subject_status == SUBJECT_NONE
