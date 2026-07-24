"""Unit tests for the golden-dataset validation gate (M06 Step 7, AC-M06-06).

Proves the MECHANISM: the reference model passes its own golden set, and a
model that regresses keypoint accuracy beyond tolerance is BLOCKED.
"""

from __future__ import annotations

from pose_service.domain.keypoints import FrameDetections, Keypoint, PersonDetection
from pose_service.domain.model import MODEL_VERSION, FakePoseModel
from pose_service.domain.validation import (
    DEFAULT_TOLERANCE,
    build_golden_from_reference,
    run_validation,
)

GEOMETRIES = [("side_on_a", 12, 1920, 1080), ("side_on_b", 8, 1280, 720)]


class RegressedModel:
    """A model that distorts the skeleton's RELATIVE geometry — a real regression.

    Shifts every joint EXCEPT the ankles. Because normalisation is
    origin-relative (origin = ankle midpoint), a global translation would
    cancel out; moving the body relative to the ankles genuinely changes the
    normalised pose and so must be caught by the gate.
    """

    version = "regressed-vX"

    def __init__(self, shift_px: float) -> None:
        self._shift = shift_px
        self._base = FakePoseModel()

    def infer(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        frames = self._base.infer(frame_count=frame_count, width=width, height=height)
        out: list[FrameDetections] = []
        for fr in frames:
            persons = tuple(
                PersonDetection(
                    keypoints=tuple(
                        Keypoint(
                            joint=k.joint,
                            x=k.x + (0.0 if k.joint.endswith("ankle") else self._shift),
                            y=k.y,
                            confidence=k.confidence,
                        )
                        for k in p.keypoints
                    ),
                    score=p.score,
                    cx=p.cx,
                    cy=p.cy,
                    area=p.area,
                )
                for p in fr.persons
            )
            out.append(FrameDetections(frame_index=fr.frame_index, persons=persons))
        return out


class RejectingModel:
    """A broken model that finds no usable subject on any clip."""

    version = "broken-vX"

    def infer(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
        return [FrameDetections(frame_index=i, persons=()) for i in range(frame_count)]


class TestGate:
    def test_reference_model_passes_its_own_golden(self) -> None:
        good = FakePoseModel()
        golden = build_golden_from_reference(good, GEOMETRIES)
        report = run_validation(good, golden)
        assert report.mean_error < 1e-9
        assert report.passed is True
        assert set(report.per_sample) == {"side_on_a", "side_on_b"}

    def test_regressed_model_is_blocked(self) -> None:
        golden = build_golden_from_reference(FakePoseModel(), GEOMETRIES)
        # Shift by ~0.2 of frame height -> normalised error ~0.2 >> tolerance.
        report = run_validation(RegressedModel(shift_px=220.0), golden)
        assert report.mean_error > DEFAULT_TOLERANCE
        assert report.passed is False

    def test_rejecting_model_is_blocked(self) -> None:
        golden = build_golden_from_reference(FakePoseModel(), GEOMETRIES)
        report = run_validation(RejectingModel(), golden)
        assert report.passed is False  # no comparable frames -> max error

    def test_model_version_pinned(self) -> None:
        assert FakePoseModel().version == MODEL_VERSION
