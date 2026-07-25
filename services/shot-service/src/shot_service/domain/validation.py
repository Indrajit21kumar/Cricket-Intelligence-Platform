"""Golden-dataset validation gate for the classifier (M09 Step 6, ENG-007).

A classifier change MUST NOT ship if it regresses accuracy OR its confusion
profile (AC-M09-07, NFR-M09-04). This gate measures THREE things, because a
shot classifier can pass a naive accuracy check while still being dangerous:

- **Accuracy.** Fraction of labelled strokes classified correctly, counting
  only the ones the classifier committed to (see abstention below).
- **Dangerous confusion.** A model can hit high overall accuracy while
  systematically confusing one specific pair — calling every pull a hook, say.
  Overall accuracy hides that; M10 would then apply the wrong benchmarks
  consistently for that shot. So each ordered pair (true → predicted) is bounded
  separately, and any pair exceeding the cap fails regardless of the headline
  number (§13).
- **Abstention rate.** Abstention is correct behaviour, but a classifier that
  abstains on everything trivially never gets anything WRONG. Left unchecked,
  "abstain always" would pass an accuracy-only gate. So the fraction of
  abstentions is capped: a model has to actually commit often enough to be
  useful.

The golden corpus is labelled shot data that does not exist yet (M09 is Green-
tier but still data-gated). The gate is built and tested against a labelled
fixture set and wired into CI, so it starts blocking the moment real data lands.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from shot_service.domain.abstention import MIN_CONFIDENCE, MIN_MARGIN
from shot_service.domain.classifier import ShotClassifier
from shot_service.domain.features import ShotFeatures
from shot_service.domain.shot import UNCLASSIFIED, Classification

#: Minimum fraction of COMMITTED classifications that must be correct.
DEFAULT_MIN_ACCURACY = 0.80

#: No single (true -> predicted) confusion may exceed this fraction of that
#: true class's samples. Catches a systematic pair confusion an accuracy
#: number would average away.
DEFAULT_MAX_PAIR_CONFUSION = 0.25

#: A classifier may not abstain on more than this fraction of the golden set —
#: otherwise "abstain always" trivially passes the accuracy gate.
DEFAULT_MAX_ABSTENTION_RATE = 0.35


@dataclass(frozen=True, slots=True)
class GoldenSample:
    """One labelled stroke: its features and the true shot class."""

    name: str
    features: ShotFeatures
    true_class: str


@dataclass(frozen=True, slots=True)
class ValidationReport:
    accuracy: float
    abstention_rate: float
    #: (true_class, predicted_class) -> fraction of true_class predicted so.
    worst_confusion: tuple[str, str, float] | None
    passed: bool
    min_accuracy: float
    max_pair_confusion: float
    max_abstention_rate: float
    #: accuracy | confusion | abstention_rate | empty_golden_set — None if passed.
    reason: str | None
    per_true_class: dict[str, int] = field(default_factory=dict)


def run_validation(
    classifier: ShotClassifier,
    golden: list[GoldenSample],
    *,
    min_accuracy: float = DEFAULT_MIN_ACCURACY,
    max_pair_confusion: float = DEFAULT_MAX_PAIR_CONFUSION,
    max_abstention_rate: float = DEFAULT_MAX_ABSTENTION_RATE,
) -> ValidationReport:
    """Score a candidate classifier against the golden set. Blocks on regression."""
    if not golden:
        # No evidence must never read as evidence of no regression.
        return ValidationReport(
            accuracy=0.0,
            abstention_rate=1.0,
            worst_confusion=None,
            passed=False,
            min_accuracy=min_accuracy,
            max_pair_confusion=max_pair_confusion,
            max_abstention_rate=max_abstention_rate,
            reason="empty_golden_set",
        )

    total = len(golden)
    abstained = 0
    committed = 0
    correct = 0
    true_counts: Counter[str] = Counter()
    confusion: Counter[tuple[str, str]] = Counter()

    for sample in golden:
        true_counts[sample.true_class] += 1
        prediction = classifier.classify(sample.features)
        # A committed classification is one strong enough to be emitted — the
        # gate must judge the classifier as it would actually behave, so it
        # applies the same abstention rule the runtime does.
        predicted = _committed_class(prediction)
        if predicted == UNCLASSIFIED:
            abstained += 1
            continue
        committed += 1
        if predicted == sample.true_class:
            correct += 1
        else:
            confusion[(sample.true_class, predicted)] += 1

    accuracy = (correct / committed) if committed else 0.0
    abstention_rate = abstained / total

    worst_confusion: tuple[str, str, float] | None = None
    worst_fraction = 0.0
    for (true_class, predicted), count in confusion.items():
        fraction = count / true_counts[true_class]
        if fraction > worst_fraction:
            worst_fraction = fraction
            worst_confusion = (true_class, predicted, fraction)

    reason: str | None = None
    if abstention_rate > max_abstention_rate:
        reason = "abstention_rate"
    elif accuracy < min_accuracy:
        reason = "accuracy"
    elif worst_fraction > max_pair_confusion:
        reason = "confusion"

    return ValidationReport(
        accuracy=accuracy,
        abstention_rate=abstention_rate,
        worst_confusion=worst_confusion,
        passed=reason is None,
        min_accuracy=min_accuracy,
        max_pair_confusion=max_pair_confusion,
        max_abstention_rate=max_abstention_rate,
        reason=reason,
        per_true_class=dict(true_counts),
    )


def _committed_class(prediction: Classification) -> str:
    """Apply the runtime abstention rule so the gate judges real behaviour.

    Uses the same thresholds as :mod:`shot_service.domain.abstention`
    deliberately: the gate must measure the classifier the way it will actually
    be used, abstention and all.
    """
    if prediction.confidence < MIN_CONFIDENCE or prediction.runner_up_margin < MIN_MARGIN:
        return UNCLASSIFIED
    return prediction.shot_class
