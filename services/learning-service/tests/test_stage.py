"""Learning-stage inference (M17 Step 2, FR-M17-01, AC-M17-01)."""

from __future__ import annotations

from learning_service.domain.stage import (
    ASSOCIATIVE,
    AUTONOMOUS,
    COGNITIVE,
    LearningSignals,
    compute_consistency,
    compute_improvement_rate,
    infer_stage,
)


class TestComputeConsistency:
    def test_no_deviations_is_honestly_unknown(self) -> None:
        assert compute_consistency([]) is None

    def test_zero_deviation_is_perfectly_consistent(self) -> None:
        assert compute_consistency([0.0, 0.0, 0.0]) == 1.0

    def test_larger_deviations_yield_lower_consistency(self) -> None:
        low_dev = compute_consistency([0.1, 0.2])
        high_dev = compute_consistency([2.0, 3.0])
        assert low_dev is not None and high_dev is not None
        assert low_dev > high_dev

    def test_sign_does_not_matter_only_magnitude(self) -> None:
        assert compute_consistency([1.0, 1.0]) == compute_consistency([-1.0, -1.0])


class TestComputeImprovementRate:
    def test_no_history_is_honestly_unknown(self) -> None:
        assert compute_improvement_rate([]) is None

    def test_mean_of_absolute_deltas(self) -> None:
        assert compute_improvement_rate([2.0, 4.0]) == 3.0

    def test_negative_and_positive_deltas_both_count_as_movement(self) -> None:
        assert compute_improvement_rate([-4.0, 4.0]) == 4.0


class TestInferStage:
    def test_no_signals_at_all_defaults_to_cognitive(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=None, improvement_rate=None))
        assert estimate.stage == COGNITIVE

    def test_low_consistency_is_cognitive(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=0.2, improvement_rate=0.3))
        assert estimate.stage == COGNITIVE

    def test_moderate_consistency_is_associative(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=0.6, improvement_rate=0.3))
        assert estimate.stage == ASSOCIATIVE

    def test_high_consistency_and_stabilised_improvement_is_autonomous(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=0.9, improvement_rate=0.01))
        assert estimate.stage == AUTONOMOUS

    def test_high_consistency_but_still_improving_a_lot_is_not_autonomous_yet(self) -> None:
        """High consistency alone isn't enough — traits must have stabilised too."""
        estimate = infer_stage(LearningSignals(consistency=0.9, improvement_rate=0.5))
        assert estimate.stage == ASSOCIATIVE

    def test_high_consistency_with_unknown_improvement_rate_is_not_autonomous(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=0.9, improvement_rate=None))
        assert estimate.stage == ASSOCIATIVE

    def test_estimate_carries_the_signals_that_produced_it(self) -> None:
        estimate = infer_stage(LearningSignals(consistency=0.6, improvement_rate=0.2))
        assert estimate.consistency == 0.6
        assert estimate.improvement_rate == 0.2
