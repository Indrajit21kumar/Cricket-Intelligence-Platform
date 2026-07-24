"""Bat-detector validation gate (M07 Step 8, AC-M07-06, ENG-007).

The gate's job is to BLOCK. These tests prove it blocks for the two ways a
detector can regress — worse localisation, and quietly detecting less — and
that it does not block a detector matching the reference.
"""

from __future__ import annotations

import math

from bat_service.domain.bat import BLADE_TIP, HANDLE_BOTTOM, HANDLE_TOP, BatPart, FrameDetections
from bat_service.domain.detector import MODEL_VERSION, FakeBatDetector
from bat_service.domain.validation import (
    DEFAULT_MIN_DETECTION_RATE,
    DEFAULT_TOLERANCE,
    build_golden_from_reference,
    run_validation,
)

GEOMETRIES = [
    ("golden-side-on-a", 20, 1920, 1080),
    ("golden-side-on-b", 24, 1280, 720),
]


class TestGate:
    def test_reference_detector_passes_its_own_golden(self) -> None:
        detector = FakeBatDetector()
        golden = build_golden_from_reference(detector, GEOMETRIES)
        report = run_validation(detector, golden)
        assert report.passed is True
        assert report.mean_error == 0.0
        assert report.detection_rate == 1.0
        assert report.reason is None

    def test_regressed_localisation_is_blocked(self) -> None:
        """A detector that puts the blade in the wrong place must not ship."""
        golden = build_golden_from_reference(FakeBatDetector(), GEOMETRIES)

        class DriftingDetector:
            """Same detections, blade tip pushed well off true."""

            version = MODEL_VERSION
            dataset_version = None

            def detect(self, *, frame_count: int, width: int, height: int) -> list[FrameDetections]:
                frames = FakeBatDetector().detect(
                    frame_count=frame_count, width=width, height=height
                )
                shifted: list[FrameDetections] = []
                for fr in frames:
                    bats = []
                    for bat in fr.bats:
                        parts = tuple(
                            BatPart(
                                part=p.part,
                                # Move the blade only: a global shift would be
                                # invisible once tracking re-centres the frame.
                                x=p.x + (0.20 * height if p.part == BLADE_TIP else 0.0),
                                y=p.y,
                                confidence=p.confidence,
                                provenance=p.provenance,
                            )
                            for p in bat.parts
                        )
                        bats.append(type(bat)(parts=parts, score=bat.score))
                    shifted.append(FrameDetections(frame_index=fr.frame_index, bats=tuple(bats)))
                return shifted

        report = run_validation(DriftingDetector(), golden)
        assert report.passed is False
        assert report.reason in {"localisation", "both"}
        assert report.mean_error > DEFAULT_TOLERANCE

    def test_a_detector_that_stops_detecting_is_blocked(self) -> None:
        """The failure mode a pure error metric would reward.

        Dropping most frames makes mean error LOOK better — only the frames it
        kept get measured — so the gate checks detection rate as well.
        """
        golden = build_golden_from_reference(FakeBatDetector(), GEOMETRIES)
        lazy = FakeBatDetector(fail_frames=frozenset(range(4, 24)))

        report = run_validation(lazy, golden)
        assert report.detection_rate < DEFAULT_MIN_DETECTION_RATE
        assert report.passed is False
        assert report.reason in {"detection_rate", "both"}
        # The point: its localisation on surviving frames was perfect.
        assert report.mean_error == 0.0

    def test_a_detector_that_finds_nothing_is_blocked(self) -> None:
        golden = build_golden_from_reference(FakeBatDetector(), GEOMETRIES)
        blind = FakeBatDetector(fail_frames=frozenset(range(64)))
        report = run_validation(blind, golden)
        assert report.passed is False
        assert report.mean_error == math.inf

    def test_an_empty_golden_set_is_not_a_pass(self) -> None:
        """No evidence must never read as evidence of no regression."""
        report = run_validation(FakeBatDetector(), [])
        assert report.passed is False
        assert report.reason == "empty_golden_set"

    def test_model_version_is_pinned(self) -> None:
        """The gate keys off a pinned version; a retrain must bump it."""
        assert FakeBatDetector().version == MODEL_VERSION

    def test_report_carries_per_sample_detail(self) -> None:
        """A failing gate must say which clips regressed, not just that it did."""
        detector = FakeBatDetector()
        golden = build_golden_from_reference(detector, GEOMETRIES)
        report = run_validation(detector, golden)
        assert set(report.per_sample) == {name for name, _, _, _ in GEOMETRIES}


class TestPartsPresence:
    def test_golden_truth_captures_every_part(self) -> None:
        golden = build_golden_from_reference(FakeBatDetector(), GEOMETRIES[:1])
        detected = [f for f in golden[0].truth_frames if f]
        assert detected
        names = {p.part for p in detected[0]}
        assert {HANDLE_TOP, HANDLE_BOTTOM, BLADE_TIP} <= names
