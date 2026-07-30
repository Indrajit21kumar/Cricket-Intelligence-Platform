"""Confidence-weighted decay/EMA trait update (M16 Step 3, FR-M16-02/03)."""

from __future__ import annotations

import pytest

from dna_service.domain.decay import DECAY, update_trait


class TestFirstObservation:
    def test_no_prior_value_the_trait_becomes_the_evidence(self) -> None:
        result = update_trait(
            trait_key="trait.balance",
            prior_value=None,
            prior_confidence=None,
            evidence_value=80.0,
            evidence_confidence=0.7,
        )
        assert result.new_value == 80.0
        assert result.new_confidence == 0.7


class TestEMAUpdate:
    def test_full_confidence_matches_plain_ema(self) -> None:
        result = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=1.0,
            decay=0.7,
        )
        expected = 0.7 * 70.0 + 0.3 * 90.0
        assert result.new_value == pytest.approx(expected)

    def test_zero_confidence_evidence_leaves_the_value_unchanged(self) -> None:
        result = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=0.0,
        )
        assert result.new_value == 70.0
        assert result.new_confidence == 0.8

    def test_low_confidence_evidence_moves_the_trait_less_than_high_confidence(self) -> None:
        low = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=0.2,
        )
        high = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=0.9,
        )
        low_move = abs(low.new_value - 70.0)
        high_move = abs(high.new_value - 70.0)
        assert low_move < high_move

    def test_confidence_blends_with_the_same_weight_as_the_value(self) -> None:
        result = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.5,
            evidence_value=90.0,
            evidence_confidence=1.0,
            decay=0.7,
        )
        expected_confidence = 0.7 * 0.5 + 0.3 * 1.0
        assert result.new_confidence == pytest.approx(expected_confidence)

    def test_default_decay_is_the_module_constant(self) -> None:
        with_default = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=1.0,
        )
        with_explicit = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.8,
            evidence_value=90.0,
            evidence_confidence=1.0,
            decay=DECAY,
        )
        assert with_default.new_value == with_explicit.new_value

    def test_result_records_the_prior_and_evidence_confidence(self) -> None:
        result = update_trait(
            trait_key="trait.balance",
            prior_value=70.0,
            prior_confidence=0.6,
            evidence_value=90.0,
            evidence_confidence=0.9,
        )
        assert result.prior_value == 70.0
        assert result.prior_confidence == 0.6
        assert result.evidence_confidence == 0.9
