"""Shot-classifier adapter + fake + pinned registry version (M09 §11, FR-M09-07).

M09 is Green-tier — pose-based shot classification is demonstrated at high
accuracy in the literature — but a real classifier still needs a labelled shot
corpus, which does not exist yet. So the classifier sits behind this protocol
with a deterministic fake, and everything around it (feature building,
abstention, phase segmentation, fusion) is real.

The fake is NOT a lookup table. It scores every class with transparent,
inspectable rules over the feature vector — footedness, swing-plane
inclination, contact height, wrist travel — and returns a full ranked
distribution. That matters because the abstention logic (Step 3) reasons over
the distribution's SHAPE (top score and runner-up margin), so the fake has to
produce a realistic distribution, not just a winner. A trained sequence model
drops in behind the same interface, returning the same distribution shape.

Deliberately, the fake classifies LESS confidently without bat/ball signals.
That is not a trick to satisfy a test: pose alone genuinely disambiguates
fewer shots (a cover drive and an on drive look similar without the bat's
swing plane), so the confidence honestly reflects the poorer evidence, and the
pose-only path drifts toward abstention exactly as it should.
"""

from __future__ import annotations

import math
from typing import Protocol

from shot_service.domain.features import ShotFeatures
from shot_service.domain.shot import (
    COVER_DRIVE,
    CUT,
    DEFENSIVE,
    FLICK,
    HOOK,
    LOFTED,
    ON_DRIVE,
    PULL,
    REVERSE_SWEEP,
    SHOT_CLASSES,
    STRAIGHT_DRIVE,
    SWEEP,
    Classification,
    ClassScore,
)

#: Pinned classifier version. A retrain bumps this and must clear the gate.
MODEL_VERSION = "fake-shot-v1"
#: The labelled corpus this classifier was trained on. None until one exists.
DATASET_VERSION: str | None = None

#: Confidence penalty applied when the bat signal is missing, since pose alone
#: separates fewer shots. Ball adds a smaller refinement.
NO_BAT_PENALTY = 0.75
NO_BALL_PENALTY = 0.9


class ShotClassifier(Protocol):
    """Adapter every shot classifier (trained model or fake) satisfies."""

    @property
    def version(self) -> str:
        """Registry version pinned to this classifier."""
        ...

    @property
    def dataset_version(self) -> str | None:
        """Labelled dataset this classifier was trained on, if known."""
        ...

    def classify(self, features: ShotFeatures) -> Classification:
        """Score the stroke against the taxonomy, returning a full distribution."""
        ...


def _softmax(raw: dict[str, float]) -> list[ClassScore]:
    """Turn rule scores into a normalised distribution."""
    if not raw:
        return []
    top = max(raw.values())
    exps = {k: math.exp(v - top) for k, v in raw.items()}
    total = sum(exps.values())
    return [ClassScore(shot_class=k, score=v / total) for k, v in exps.items()]


class FakeShotClassifier:
    """Deterministic rule-based classifier for dev + tests.

    Scores are geometric affinities, not certainties: several shots always get
    some score, so the returned distribution has a realistic runner-up margin
    for the abstention logic to inspect.
    """

    def __init__(self) -> None:
        self._version = MODEL_VERSION
        self._dataset_version = DATASET_VERSION

    @property
    def version(self) -> str:
        return self._version

    @property
    def dataset_version(self) -> str | None:
        return self._dataset_version

    def classify(self, features: ShotFeatures) -> Classification:
        raw = self._score(features)
        scores = tuple(sorted(_softmax(raw), key=lambda s: s.score, reverse=True))
        if not scores:
            return Classification(shot_class="", confidence=0.0, scores=())

        top = scores[0]
        confidence = top.score
        # Poorer evidence, lower confidence — pose alone genuinely separates
        # fewer shots, and the value should say so.
        if not features.has_bat:
            confidence *= NO_BAT_PENALTY
        if not features.has_ball:
            confidence *= NO_BALL_PENALTY
        return Classification(
            shot_class=top.shot_class,
            confidence=max(0.0, min(1.0, confidence)),
            scores=scores,
        )

    def _score(self, f: ShotFeatures) -> dict[str, float]:
        """Transparent geometric affinities per class."""
        incl = f.swing_plane_inclination
        vertical_bat = incl is not None and incl < 35.0
        horizontal_bat = incl is not None and incl > 60.0

        raw: dict[str, float] = {}

        # Vertical-ish swing, front foot forward, ball driven: the drives.
        drive_base = 2.0 + max(f.footedness, 0.0) * 1.5
        if vertical_bat:
            drive_base += 1.0
        raw[STRAIGHT_DRIVE] = drive_base
        raw[COVER_DRIVE] = drive_base + max(f.wrist_lateral_travel, 0.0) * 2.0
        raw[ON_DRIVE] = drive_base + max(-f.wrist_lateral_travel, 0.0) * 2.0

        # Front foot, worked to the on side off the hip: the flick.
        raw[FLICK] = drive_base + max(-f.wrist_lateral_travel, 0.0) * 1.2 - 0.5

        # Horizontal-bat, back foot, higher contact: the cross-bat shots.
        cross_base = 2.0 + max(-f.footedness, 0.0) * 1.5
        if horizontal_bat:
            cross_base += 1.0
        raw[PULL] = cross_base + max(f.contact_height, 0.0) * 1.5
        raw[HOOK] = cross_base + max(f.contact_height - 0.3, 0.0) * 3.0
        raw[CUT] = cross_base + max(f.wrist_lateral_travel, 0.0) * 1.5

        # Low contact + horizontal bat: the sweeps.
        sweep_base = 1.5 + max(-f.contact_height, 0.0) * 2.5
        raw[SWEEP] = sweep_base
        raw[REVERSE_SWEEP] = sweep_base + max(f.wrist_lateral_travel, 0.0) * 1.0

        # High wrist peak: lofted.
        raw[LOFTED] = 1.5 + max(f.wrist_peak_height - 0.4, 0.0) * 4.0

        # Little travel, little rotation: defensive.
        stillness = max(0.0, 1.0 - f.wrist_lateral_travel - f.shoulder_rotation / 90.0)
        raw[DEFENSIVE] = 1.5 + stillness * 2.5

        # Every class carries some mass so the distribution spans the whole
        # taxonomy — the confusion gate (Step 6) needs every class represented.
        for shot_class in SHOT_CLASSES:
            raw.setdefault(shot_class, 0.5)
        return raw
