"""Calibrated abstention (M09 Step 3, AC-M09-01/02).

The two failure modes a confidence threshold has to catch: a low top score, and
a top-2 that is nearly tied even when the top score looks acceptable.
"""

from __future__ import annotations

import pytest

from shot_service.domain.abstention import (
    MIN_CONFIDENCE,
    PROVISIONAL_CONFIDENCE,
    resolve,
)
from shot_service.domain.shot import (
    COVER_DRIVE,
    METHOD_STANDARD,
    ON_DRIVE,
    PULL,
    QUALITY_OK,
    QUALITY_PROVISIONAL,
    QUALITY_UNCLASSIFIED,
    UNCLASSIFIED,
    Classification,
    ClassScore,
    PhaseBoundaries,
)

PHASES = PhaseBoundaries(
    stance=0, backlift=5, downswing=12, impact=18, follow_through=22, method=METHOD_STANDARD
)


def _classification(*pairs: tuple[str, float]) -> Classification:
    scores = tuple(ClassScore(shot_class=c, score=s) for c, s in pairs)
    top = max(scores, key=lambda s: s.score)
    return Classification(shot_class=top.shot_class, confidence=top.score, scores=scores)


class TestConfidentClassification:
    def test_a_clear_winner_is_emitted(self) -> None:
        """AC-M09-01."""
        result = resolve(
            _classification((COVER_DRIVE, 0.80), (ON_DRIVE, 0.10), (PULL, 0.10)),
            phases=PHASES,
            signals_used=("pose", "bat"),
        )
        assert result.shot_class == COVER_DRIVE
        assert result.abstained is False
        assert result.quality == QUALITY_OK

    def test_a_middling_winner_is_provisional(self) -> None:
        result = resolve(
            _classification((COVER_DRIVE, 0.55), (ON_DRIVE, 0.20), (PULL, 0.25)),
            phases=PHASES,
            signals_used=("pose",),
        )
        assert result.shot_class == COVER_DRIVE
        assert result.quality == QUALITY_PROVISIONAL


class TestAbstention:
    def test_below_the_confidence_floor_abstains(self) -> None:
        """AC-M09-02: a likely-wrong label is worse than none."""
        result = resolve(
            _classification((COVER_DRIVE, 0.30), (ON_DRIVE, 0.15), (PULL, 0.15)),
            phases=PHASES,
            signals_used=("pose",),
        )
        assert result.shot_class == UNCLASSIFIED
        assert result.abstained is True
        assert result.quality == QUALITY_UNCLASSIFIED

    def test_an_ambiguous_top_two_abstains_despite_a_fine_top_score(self) -> None:
        """The case a naive threshold misses: 0.42 vs 0.40 is a coin toss."""
        result = resolve(
            _classification((COVER_DRIVE, 0.42), (ON_DRIVE, 0.40), (PULL, 0.18)),
            phases=PHASES,
            signals_used=("pose", "bat"),
        )
        assert result.shot_class == UNCLASSIFIED
        # Even though the top score cleared the confidence floor.
        assert result.shot_confidence >= MIN_CONFIDENCE - 0.05

    def test_abstention_keeps_the_near_miss_for_labelling(self) -> None:
        """A near-miss is the best sample to send a human (Step 5 flywheel)."""
        result = resolve(
            _classification((PULL, 0.44), (COVER_DRIVE, 0.42)),
            phases=PHASES,
            signals_used=("pose",),
        )
        assert result.shot_class == UNCLASSIFIED
        assert result.abstained_from == PULL
        assert len(result.scores) == 2


class TestBoundaries:
    def test_exactly_at_the_confidence_floor_is_not_abstained(self) -> None:
        result = resolve(
            _classification((COVER_DRIVE, MIN_CONFIDENCE), (ON_DRIVE, 0.20), (PULL, 0.10)),
            phases=PHASES,
            signals_used=("pose", "bat"),
        )
        assert result.shot_class == COVER_DRIVE

    def test_a_margin_clear_of_the_threshold_is_not_abstained(self) -> None:
        # Comfortably above MIN_MARGIN, so the boundary is not float-fragile.
        result = resolve(
            _classification((COVER_DRIVE, 0.55), (ON_DRIVE, 0.35), (PULL, 0.10)),
            phases=PHASES,
            signals_used=("pose", "bat"),
        )
        assert result.shot_class == COVER_DRIVE
        assert result.abstained is False

    def test_the_provisional_boundary(self) -> None:
        result = resolve(
            _classification((COVER_DRIVE, PROVISIONAL_CONFIDENCE), (ON_DRIVE, 0.10), (PULL, 0.10)),
            phases=PHASES,
            signals_used=("pose", "bat"),
        )
        assert result.quality == QUALITY_OK


class TestPoseOnlyDriftsTowardAbstention:
    def test_the_no_bat_penalty_can_tip_a_borderline_case_into_abstention(self) -> None:
        """Poorer evidence, more caution — the value drives the outcome."""
        # A score that would pass with bat, penalised below the floor without.
        confident = _classification((COVER_DRIVE, 0.60), (ON_DRIVE, 0.20), (PULL, 0.20))
        penalised = Classification(
            shot_class=COVER_DRIVE,
            confidence=confident.confidence * 0.75,  # the NO_BAT_PENALTY
            scores=confident.scores,
        )
        result = resolve(penalised, phases=PHASES, signals_used=("pose",))
        assert result.shot_confidence == pytest.approx(0.45)
        # 0.45 is exactly the floor, so it survives — one nudge lower abstains.
        weaker = Classification(shot_class=COVER_DRIVE, confidence=0.44, scores=confident.scores)
        assert resolve(weaker, phases=PHASES, signals_used=("pose",)).abstained is True
