"""Fault prioritisation: impact x fixability x stage-readiness (M17 Step 3, FR-M17-02)."""

from __future__ import annotations

from learning_service.domain.prioritization import prioritize_faults


def _finding(
    finding_id: str,
    *,
    confidence: float = 0.9,
    provenance: str = "measured",
    metric_ids: list[str] | None = None,
) -> dict:
    return {
        "finding_id": finding_id,
        "confidence": confidence,
        "provenance": provenance,
        "evidence": [{"metric_id": m, "value": 1.0} for m in (metric_ids or [])],
    }


class TestImpact:
    def test_higher_confidence_finding_scores_higher_impact(self) -> None:
        results = prioritize_faults(
            [_finding("F::A", confidence=0.9), _finding("F::B", confidence=0.3)],
            stage="associative",
        )
        by_id = {r.finding_id: r for r in results}
        assert by_id["F::A"].impact > by_id["F::B"].impact


class TestFixability:
    def test_measured_is_more_fixable_than_modelled(self) -> None:
        results = prioritize_faults(
            [
                _finding("F::MEASURED", provenance="measured"),
                _finding("F::MODELLED", provenance="modelled"),
            ],
            stage="associative",
        )
        by_id = {r.finding_id: r for r in results}
        assert by_id["F::MEASURED"].fixability > by_id["F::MODELLED"].fixability

    def test_unknown_provenance_falls_back_to_default(self) -> None:
        results = prioritize_faults([_finding("F::X", provenance="mystery")], stage="associative")
        assert results[0].fixability == 0.5


class TestReadiness:
    def test_foundational_category_is_full_readiness_at_cognitive_stage(self) -> None:
        results = prioritize_faults([_finding("F::BAL", metric_ids=["BM-01"])], stage="cognitive")
        assert results[0].readiness == 1.0
        assert results[0].categories == ("balance",)

    def test_power_category_is_off_focus_at_cognitive_stage(self) -> None:
        results = prioritize_faults([_finding("F::POW", metric_ids=["PH-08"])], stage="cognitive")
        assert results[0].readiness < 1.0

    def test_power_category_is_full_readiness_at_autonomous_stage(self) -> None:
        results = prioritize_faults([_finding("F::POW", metric_ids=["PH-08"])], stage="autonomous")
        assert results[0].readiness == 1.0

    def test_finding_with_no_metric_ids_defaults_to_technique(self) -> None:
        results = prioritize_faults([_finding("F::NONE", metric_ids=[])], stage="associative")
        assert results[0].categories == ("technique",)


class TestPrioritizeFaults:
    def test_ranked_highest_score_first(self) -> None:
        strong = _finding("F::STRONG", confidence=1.0, provenance="measured", metric_ids=["BM-01"])
        weak = _finding("F::WEAK", confidence=0.2, provenance="modelled", metric_ids=["PH-08"])
        results = prioritize_faults([weak, strong], stage="cognitive")
        assert [r.finding_id for r in results] == ["F::STRONG", "F::WEAK"]

    def test_a_finding_without_a_finding_id_is_skipped(self) -> None:
        results = prioritize_faults([{"confidence": 0.9}], stage="associative")
        assert results == []

    def test_no_findings_yields_no_priorities(self) -> None:
        assert prioritize_faults([], stage="associative") == []

    def test_unknown_stage_gets_the_off_focus_readiness_for_everything(self) -> None:
        results = prioritize_faults(
            [_finding("F::X", metric_ids=["BM-01"])], stage="not-a-real-stage"
        )
        assert results[0].readiness == 0.6
