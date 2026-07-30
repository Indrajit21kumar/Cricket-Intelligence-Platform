"""Finding assembly + evidence links (M13 Step 6, §5, FR-M13-05, AC-M13-02)."""

from __future__ import annotations

from reasoning_service.domain.engine import FiredRule
from reasoning_service.domain.facts import Fact
from reasoning_service.domain.findings import assemble_finding, assemble_findings


def _fact(mid: str, val: float, conf: float, *, provenance: str = "measured") -> Fact:
    return Fact(metric_id=mid, value=val, confidence=conf, provenance=provenance)


def _fired(rule_id: str, *facts: Fact, **extra: object) -> FiredRule:
    kwargs = {
        "rule_id": rule_id,
        "version": 1,
        "rule_confidence": 0.9,
        "fault": "head falling outside off",
        "cause": "weight staying back",
        "risk": {"statement": "LBW risk"},
        "drill": {"name": "closed-shoulder drill", "objective": "head over knee 8/10"},
        "evidence": {"tier": 1, "validated_by": {"reviewer": "SAB"}},
        "triggering": tuple(facts),
    }
    kwargs.update(extra)
    return FiredRule(**kwargs)  # type: ignore[arg-type]


class TestAssembleFinding:
    def test_finding_carries_what_why_impact_drill(self) -> None:
        finding = assemble_finding(
            _fired("KG-A", _fact("BM-17", 60.0, 0.75), _fact("BM-01", 5.0, 0.9)),
            report_provisional=False,
        )
        assert finding.what == "head falling outside off"
        assert finding.why == "weight staying back"
        assert finding.impact["statement"] == "LBW risk"
        assert finding.drill["objective"]

    def test_evidence_links_trace_to_triggering_metrics(self) -> None:
        """AC-M13-02: each finding links to its exact metrics + rule id/version."""
        finding = assemble_finding(
            _fired("KG-A", _fact("BM-17", 60.0, 0.75), _fact("BM-01", 5.0, 0.9)),
            report_provisional=False,
        )
        assert [e.metric_id for e in finding.evidence] == ["BM-17", "BM-01"]
        assert [e.value for e in finding.evidence] == [60.0, 5.0]
        payload = finding.to_dict()
        assert payload["citation"] == {"rule_id": "KG-A", "version": 1}

    def test_confidence_combined_from_rule_and_weakest_metric(self) -> None:
        finding = assemble_finding(
            _fired("KG-A", _fact("BM-17", 60.0, 0.75), _fact("PH-06", 42.0, 0.66)),
            report_provisional=False,
        )
        # 0.9 * 0.66 = 0.594.
        assert finding.confidence == 0.594

    def test_provenance_estimated_when_any_fact_estimated(self) -> None:
        finding = assemble_finding(
            _fired("KG-A", _fact("PH-06", 42.0, 0.66, provenance="estimated")),
            report_provisional=False,
        )
        assert finding.provenance == "estimated"

    def test_provisional_when_report_provisional(self) -> None:
        finding = assemble_finding(
            _fired("KG-A", _fact("BM-01", 5.0, 0.9)), report_provisional=True
        )
        assert finding.provisional is True

    def test_rule_evidence_book10_carried_through(self) -> None:
        finding = assemble_finding(
            _fired("KG-A", _fact("BM-01", 5.0, 0.9)), report_provisional=False
        )
        assert finding.rule_evidence["tier"] == 1
        assert finding.rule_evidence["validated_by"]["reviewer"] == "SAB"


class TestAssembleFindings:
    def test_sorted_best_confidence_first(self) -> None:
        low = _fired("KG-LOW", _fact("BM-01", 5.0, 0.4))
        high = _fired("KG-HIGH", _fact("BM-17", 60.0, 0.9))
        findings = assemble_findings([low, high], report_provisional=False)
        assert [f.rule_id for f in findings] == ["KG-HIGH", "KG-LOW"]

    def test_no_fired_no_findings(self) -> None:
        assert assemble_findings([], report_provisional=False) == []
