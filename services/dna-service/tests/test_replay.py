"""Idempotency + deterministic recompute (M16 Step 6, FR-M16-08, NFR-M16-02/03)."""

from __future__ import annotations

from dna_service.domain.decay import update_trait
from dna_service.domain.history import EvidencePoint, replay_sequence
from dna_service.domain.replay import already_processed, recompute_traits


def _evidence(*values: float) -> list[EvidencePoint]:
    return [
        EvidencePoint(value=v, confidence=0.85, source_ref=f"s{i}") for i, v in enumerate(values)
    ]


class TestRecomputeMatchesIncremental:
    def test_recompute_matches_applying_evidence_one_session_at_a_time(self) -> None:
        """AC-M16-05: the backfill/repair path reproduces the incremental result."""
        evidence = _evidence(70.0, 75.0, 80.0)

        # Incremental path: apply one at a time, feeding each result forward.
        prior_value: float | None = None
        prior_confidence: float | None = None
        for point in evidence:
            incremental = update_trait(
                trait_key="trait.balance",
                prior_value=prior_value,
                prior_confidence=prior_confidence,
                evidence_value=point.value,
                evidence_confidence=point.confidence,
            )
            prior_value = incremental.new_value
            prior_confidence = incremental.new_confidence

        # Recompute path: replay the whole history from scratch in one call.
        recomputed = recompute_traits({"trait.balance": evidence})["trait.balance"]

        assert recomputed is not None
        assert recomputed.new_value == prior_value
        assert recomputed.new_confidence == prior_confidence

    def test_replaying_the_same_sequence_twice_is_deterministic(self) -> None:
        evidence = _evidence(70.0, 75.0, 80.0)
        first = replay_sequence("trait.balance", evidence)
        second = replay_sequence("trait.balance", evidence)
        assert [r.to_dict() for r in first] == [r.to_dict() for r in second]

    def test_recompute_is_deterministic_across_calls(self) -> None:
        evidence_by_trait = {
            "trait.balance": _evidence(70.0, 80.0),
            "trait.timing": _evidence(60.0),
        }
        first = recompute_traits(evidence_by_trait)
        second = recompute_traits(evidence_by_trait)
        assert {k: v.to_dict() if v else None for k, v in first.items()} == {
            k: v.to_dict() if v else None for k, v in second.items()
        }


class TestRecomputeTraits:
    def test_multiple_traits_are_recomputed_independently(self) -> None:
        result = recompute_traits(
            {"trait.balance": _evidence(80.0), "trait.timing": _evidence(60.0)}
        )
        assert result["trait.balance"] is not None
        assert result["trait.timing"] is not None
        assert result["trait.balance"].new_value != result["trait.timing"].new_value

    def test_a_trait_with_no_evidence_recomputes_to_none(self) -> None:
        result = recompute_traits({"trait.balance": []})
        assert result["trait.balance"] is None


class TestAlreadyProcessed:
    def test_a_new_session_ref_is_not_processed(self) -> None:
        assert already_processed(["s1", "s2"], "s3") is False

    def test_a_known_session_ref_is_processed(self) -> None:
        assert already_processed(["s1", "s2"], "s2") is True

    def test_empty_processed_list_means_nothing_is_processed(self) -> None:
        assert already_processed([], "s1") is False
