"""Outlier resistance + append-only history (M16 Step 4, FR-M16-06, NFR-M16-04)."""

from __future__ import annotations

from itertools import pairwise

from dna_service.domain.decay import DECAY, update_trait
from dna_service.domain.history import EvidencePoint, replay_sequence


class TestOutlierResistance:
    def test_a_single_extreme_outlier_moves_the_trait_by_at_most_the_decay_bound(self) -> None:
        """FR-M16-06/AC-M16-04: a single session can never move a trait by more
        than (1-decay) of the gap toward it, even at maximum confidence."""
        prior = 50.0
        outlier_value = 1000.0
        result = update_trait(
            trait_key="trait.balance",
            prior_value=prior,
            prior_confidence=0.9,
            evidence_value=outlier_value,
            evidence_confidence=1.0,
        )
        max_allowed_move = (1.0 - DECAY) * abs(outlier_value - prior)
        assert abs(result.new_value - prior) <= max_allowed_move + 1e-9

    def test_established_trait_survives_one_wild_outlier_session(self) -> None:
        # Five consistent sessions establish the trait around 80.
        evidence = [EvidencePoint(value=80.0, confidence=0.9, source_ref=f"s{i}") for i in range(5)]
        history = replay_sequence("trait.balance", evidence)
        established = history[-1]

        # One session reports a wild, implausible value (e.g. a bug/glitch).
        outlier = update_trait(
            trait_key="trait.balance",
            prior_value=established.new_value,
            prior_confidence=established.new_confidence,
            evidence_value=0.0,
            evidence_confidence=1.0,
        )
        # It moved, but stayed far closer to the established value than to 0.
        assert abs(outlier.new_value - established.new_value) < abs(outlier.new_value - 0.0)

    def test_the_trait_recovers_after_the_outlier_with_the_next_normal_session(self) -> None:
        established_value = 80.0
        outlier = update_trait(
            trait_key="trait.balance",
            prior_value=established_value,
            prior_confidence=0.9,
            evidence_value=0.0,
            evidence_confidence=1.0,
        )
        recovered = update_trait(
            trait_key="trait.balance",
            prior_value=outlier.new_value,
            prior_confidence=outlier.new_confidence,
            evidence_value=established_value,
            evidence_confidence=0.9,
        )
        assert abs(recovered.new_value - established_value) < abs(
            outlier.new_value - established_value
        )

    def test_low_confidence_outlier_moves_the_trait_even_less(self) -> None:
        prior = 50.0
        full_confidence = update_trait(
            trait_key="trait.balance",
            prior_value=prior,
            prior_confidence=0.9,
            evidence_value=1000.0,
            evidence_confidence=1.0,
        )
        low_confidence = update_trait(
            trait_key="trait.balance",
            prior_value=prior,
            prior_confidence=0.9,
            evidence_value=1000.0,
            evidence_confidence=0.1,
        )
        assert abs(low_confidence.new_value - prior) < abs(full_confidence.new_value - prior)


class TestReplaySequencePreservesHistory:
    def test_replaying_n_evidence_points_yields_n_results(self) -> None:
        evidence = [
            EvidencePoint(value=v, confidence=0.8, source_ref=f"s{i}")
            for i, v in enumerate([70.0, 75.0, 80.0])
        ]
        history = replay_sequence("trait.timing", evidence)
        assert len(history) == 3

    def test_each_result_chains_to_the_previous_one(self) -> None:
        evidence = [
            EvidencePoint(value=v, confidence=0.8, source_ref=f"s{i}")
            for i, v in enumerate([70.0, 75.0, 80.0])
        ]
        history = replay_sequence("trait.timing", evidence)
        for earlier, later in pairwise(history):
            assert later.prior_value == earlier.new_value
            assert later.prior_confidence == earlier.new_confidence

    def test_first_result_has_no_prior(self) -> None:
        history = replay_sequence(
            "trait.timing", [EvidencePoint(value=70.0, confidence=0.8, source_ref="s0")]
        )
        assert history[0].prior_value is None

    def test_no_evidence_yields_no_history(self) -> None:
        assert replay_sequence("trait.timing", []) == []
