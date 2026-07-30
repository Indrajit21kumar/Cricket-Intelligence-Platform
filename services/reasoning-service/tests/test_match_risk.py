"""Match-risk output (M13 Step 7, §6, FR-M13-06, AC-M13-06)."""

from __future__ import annotations

from reasoning_service.domain.findings import Finding
from reasoning_service.domain.match_risk import PROVENANCE_MODELLED, build_match_risk


def _finding(
    *, statement: str | None, magnitude: str | None = None, context: str | None = None
) -> Finding:
    impact: dict[str, object] = {}
    if statement is not None:
        impact["statement"] = statement
    if magnitude is not None:
        impact["magnitude"] = magnitude
    if context is not None:
        impact["context"] = context
    return Finding(
        finding_id="F::KG-A:v1",
        what="head falling outside off",
        why="weight staying back",
        impact=impact,
        drill={},
        evidence=[],
        rule_id="KG-A",
        rule_version=1,
        confidence=0.7,
        provenance="measured",
    )


class TestBuildMatchRisk:
    def test_extracts_risk_bearing_findings(self) -> None:
        findings = [
            _finding(statement="LBW / inside edge", context="full outside off", magnitude="+~25%")
        ]
        risk = build_match_risk(findings)
        assert len(risk.items) == 1
        item = risk.items[0]
        assert item.statement == "LBW / inside edge"
        assert item.context == "full outside off"
        assert item.magnitude == "+~25%"
        assert item.provenance == PROVENANCE_MODELLED  # AC-M13-06

    def test_skips_findings_without_a_risk_statement(self) -> None:
        findings = [_finding(statement=None), _finding(statement="")]
        assert build_match_risk(findings).items == []

    def test_payload_is_labelled_modelled(self) -> None:
        findings = [_finding(statement="LBW risk")]
        payload = build_match_risk(findings).to_dict()
        assert payload["provenance"] == PROVENANCE_MODELLED
        assert payload["items"][0]["citation"] == {"rule_id": "KG-A", "version": 1}

    def test_finding_confidence_flows_to_the_risk_item(self) -> None:
        findings = [_finding(statement="risk")]
        assert build_match_risk(findings).items[0].confidence == 0.7

    def test_empty_findings_empty_risk(self) -> None:
        assert build_match_risk([]).items == []
