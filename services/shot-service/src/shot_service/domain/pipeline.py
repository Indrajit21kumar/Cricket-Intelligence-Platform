"""Shot classification pipeline (M09 Steps 2-4 orchestration).

One pure function, so a whole stroke can be reasoned about and tested with no
DB, GPU or broker:

    build features (pose + optional bat/ball) -> classify -> segment phases
    -> apply abstention

Step 5 wraps this with I/O (persist, publish, annotation) and adds no decisions
of its own. Phase segmentation runs REGARDLESS of the classification outcome:
an unclassified stroke still has phases M10 can use for generic handling, so
the two are computed independently and only assembled together at the end.
"""

from __future__ import annotations

from dataclasses import dataclass

from shot_service.domain.abstention import resolve
from shot_service.domain.classifier import ShotClassifier
from shot_service.domain.feature_builder import build_features
from shot_service.domain.phases import segment_phases
from shot_service.domain.shot import ShotResult
from shot_service.domain.sources import BallSummary, BatSummary, PoseSequence


@dataclass(frozen=True, slots=True)
class ShotRunResult:
    model_version: str
    dataset_version: str | None
    result: ShotResult

    @property
    def frame_count(self) -> int:
        return self.result.phases.follow_through + 1


def classify_shot(
    classifier: ShotClassifier,
    *,
    pose: PoseSequence,
    bat: BatSummary | None,
    ball: BallSummary | None,
) -> ShotRunResult:
    """Run the full shot pipeline over one stroke's derived inputs."""
    features = build_features(pose, bat=bat, ball=ball)
    classification = classifier.classify(features)
    phases = segment_phases(pose, ball=ball)
    result = resolve(classification, phases=phases, signals_used=features.signals)
    return ShotRunResult(
        model_version=classifier.version,
        dataset_version=classifier.dataset_version,
        result=result,
    )
