"""Per-session trait evidence assembly (M16 Step 2, FR-M16-01)."""

from __future__ import annotations

from dna_service.domain.evidence import gather_evidence


def _score_entry(
    value: float | None, confidence: float | None = None, unavailable_reason: str | None = None
) -> dict:
    return {
        "value": value,
        "confidence": confidence,
        "inputs": [],
        "unavailable_reason": unavailable_reason,
    }


def _report_scores(report_confidence: float = 0.8) -> dict:
    return {
        "overall": _score_entry(85.0),
        "technique": _score_entry(90.0),
        "timing": _score_entry(80.0),
        "power": _score_entry(75.0),
        "balance": _score_entry(83.0),
        "footwork": _score_entry(88.0),
        "confidence": {"value": report_confidence * 100, "confidence": report_confidence},
        "improvement": _score_entry(None, unavailable_reason="no_history"),
        "model_version": "score-std-1.0.0",
    }


class TestGatherEvidence:
    def test_one_evidence_entry_per_performance_trait(self) -> None:
        evidence = gather_evidence(report_scores=_report_scores(), source_ref="stroke-1")
        trait_keys = {e.trait_key for e in evidence}
        assert trait_keys == {"trait.timing", "trait.power", "trait.balance", "trait.footwork"}

    def test_aggression_is_never_evidenced(self) -> None:
        """No established signal for aggression anywhere in this codebase (documented scope)."""
        evidence = gather_evidence(report_scores=_report_scores(), source_ref="stroke-1")
        assert all(e.trait_key != "trait.aggression" for e in evidence)

    def test_values_come_from_the_matching_category(self) -> None:
        evidence = gather_evidence(report_scores=_report_scores(), source_ref="stroke-1")
        by_key = {e.trait_key: e for e in evidence}
        assert by_key["trait.timing"].value == 80.0
        assert by_key["trait.power"].value == 75.0
        assert by_key["trait.balance"].value == 83.0
        assert by_key["trait.footwork"].value == 88.0

    def test_confidence_is_the_report_level_confidence_for_every_trait(self) -> None:
        evidence = gather_evidence(
            report_scores=_report_scores(report_confidence=0.65), source_ref="s"
        )
        assert all(e.confidence == 0.65 for e in evidence)

    def test_provenance_is_modelled(self) -> None:
        evidence = gather_evidence(report_scores=_report_scores(), source_ref="stroke-1")
        assert all(e.provenance == "modelled" for e in evidence)

    def test_source_ref_propagates(self) -> None:
        evidence = gather_evidence(report_scores=_report_scores(), source_ref="report:abc-123")
        assert all(e.source_ref == "report:abc-123" for e in evidence)

    def test_no_report_confidence_at_all_yields_no_evidence(self) -> None:
        scores = _report_scores()
        scores["confidence"] = {"value": None, "confidence": None, "unavailable_reason": "no_facts"}
        assert gather_evidence(report_scores=scores, source_ref="stroke-1") == []

    def test_a_category_with_no_value_contributes_no_evidence(self) -> None:
        scores = _report_scores()
        scores["power"] = _score_entry(None, unavailable_reason="no_category_scores")
        evidence = gather_evidence(report_scores=scores, source_ref="stroke-1")
        assert all(e.trait_key != "trait.power" for e in evidence)
