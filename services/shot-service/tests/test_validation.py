"""Shot-classifier validation gate (M09 Step 6, AC-M09-07, ENG-007).

The gate's job is to BLOCK. These tests prove it blocks for the three ways a
shot classifier can be unfit — poor accuracy, a dangerous systematic confusion
that accuracy would hide, and abstaining its way to a good score — and that a
sound classifier passes.
"""

from __future__ import annotations

from shot_service.domain.classifier import FakeShotClassifier
from shot_service.domain.features import ShotFeatures
from shot_service.domain.shot import (
    COVER_DRIVE,
    DEFENSIVE,
    ON_DRIVE,
    PULL,
    SWEEP,
    Classification,
    ClassScore,
)
from shot_service.domain.validation import (
    DEFAULT_MAX_ABSTENTION_RATE,
    DEFAULT_MIN_ACCURACY,
    GoldenSample,
    run_validation,
)

POSE_BAT = ("pose", "bat")


def _cover() -> ShotFeatures:
    return ShotFeatures(
        frame_count=24,
        signals=POSE_BAT,
        footedness=0.8,
        wrist_lateral_travel=0.5,
        swing_plane_inclination=18.0,
        wrist_peak_height=0.72,
        contact_height=0.42,
    )


def _on_drive() -> ShotFeatures:
    return ShotFeatures(
        frame_count=24,
        signals=POSE_BAT,
        footedness=0.8,
        wrist_lateral_travel=-0.5,
        swing_plane_inclination=18.0,
        wrist_peak_height=0.72,
        contact_height=0.42,
    )


def _pull() -> ShotFeatures:
    return ShotFeatures(
        frame_count=24,
        signals=POSE_BAT,
        footedness=-0.8,
        contact_height=0.5,
        shoulder_rotation=50.0,
        swing_plane_inclination=75.0,
        wrist_peak_height=0.7,
    )


def _sweep() -> ShotFeatures:
    return ShotFeatures(
        frame_count=24,
        signals=POSE_BAT,
        footedness=0.2,
        contact_height=-0.35,
        shoulder_rotation=45.0,
        swing_plane_inclination=75.0,
        wrist_peak_height=0.5,
    )


def _defensive() -> ShotFeatures:
    return ShotFeatures(
        frame_count=24,
        signals=POSE_BAT,
        footedness=0.1,
        wrist_lateral_travel=0.02,
        shoulder_rotation=5.0,
        swing_plane_inclination=25.0,
        wrist_peak_height=0.55,
        contact_height=0.3,
    )


def _golden() -> list[GoldenSample]:
    """A small labelled set spanning distinct shot families."""
    builders = [
        (COVER_DRIVE, _cover),
        (ON_DRIVE, _on_drive),
        (PULL, _pull),
        (SWEEP, _sweep),
        (DEFENSIVE, _defensive),
    ]
    return [
        GoldenSample(name=f"{name}-{i}", features=build(), true_class=name)
        for name, build in builders
        for i in range(3)
    ]


class TestSoundClassifier:
    def test_the_reference_classifier_passes(self) -> None:
        report = run_validation(FakeShotClassifier(), _golden())
        assert report.passed is True, report.reason
        assert report.accuracy >= DEFAULT_MIN_ACCURACY
        assert report.abstention_rate <= DEFAULT_MAX_ABSTENTION_RATE


class TestBlocks:
    def test_a_dangerously_confusing_classifier_is_blocked(self) -> None:
        """The failure accuracy alone hides: every pull called a hook."""

        class ConfusingClassifier:
            version = "confuser"
            dataset_version = None

            def classify(self, features: ShotFeatures) -> Classification:
                # Confidently mislabels the cross-bat family as one wrong class.
                if features.swing_plane_inclination and features.swing_plane_inclination > 60:
                    return Classification(
                        shot_class=COVER_DRIVE,
                        confidence=0.9,
                        scores=(
                            ClassScore(COVER_DRIVE, 0.9),
                            ClassScore(PULL, 0.05),
                        ),
                    )
                return FakeShotClassifier().classify(features)

        report = run_validation(ConfusingClassifier(), _golden())
        assert report.passed is False
        assert report.reason in {"confusion", "accuracy"}
        assert report.worst_confusion is not None

    def test_an_abstain_always_classifier_is_blocked(self) -> None:
        """Abstaining on everything is never wrong — and must not pass."""

        class Abstainer:
            version = "abstainer"
            dataset_version = None

            def classify(self, features: ShotFeatures) -> Classification:
                # A flat, tied distribution -> the runtime abstention rule fires.
                _ = features
                return Classification(
                    shot_class=COVER_DRIVE,
                    confidence=0.2,
                    scores=(ClassScore(COVER_DRIVE, 0.2), ClassScore(PULL, 0.19)),
                )

        report = run_validation(Abstainer(), _golden())
        assert report.passed is False
        assert report.reason == "abstention_rate"
        assert report.abstention_rate > DEFAULT_MAX_ABSTENTION_RATE

    def test_a_low_accuracy_classifier_is_blocked(self) -> None:
        """Commits confidently but to the wrong class, spread around."""

        class WrongClassifier:
            version = "wrong"
            dataset_version = None

            def classify(self, features: ShotFeatures) -> Classification:
                # Deterministically wrong, but spread so no single pair caps out
                # before accuracy does.
                wrong = (SWEEP, DEFENSIVE, ON_DRIVE)
                idx = abs(hash(features.contact_height)) % len(wrong)
                pick = wrong[idx]
                return Classification(
                    shot_class=pick,
                    confidence=0.9,
                    scores=(ClassScore(pick, 0.9), ClassScore(COVER_DRIVE, 0.02)),
                )

        report = run_validation(WrongClassifier(), _golden())
        assert report.passed is False
        assert report.reason in {"accuracy", "confusion"}

    def test_an_empty_golden_set_is_not_a_pass(self) -> None:
        report = run_validation(FakeShotClassifier(), [])
        assert report.passed is False
        assert report.reason == "empty_golden_set"


class TestReportDetail:
    def test_report_names_the_worst_confusion_pair(self) -> None:
        report = run_validation(FakeShotClassifier(), _golden())
        # On a clean set the reference classifier has no confusion to report.
        assert report.worst_confusion is None or len(report.worst_confusion) == 3

    def test_per_true_class_counts_are_reported(self) -> None:
        report = run_validation(FakeShotClassifier(), _golden())
        assert report.per_true_class[COVER_DRIVE] == 3
