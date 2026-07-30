"""Evidence assembly for the grounded narrative (M14 Step 5, FR-M14-02)."""

from __future__ import annotations

from report_service.domain.evidence import build_evidence
from report_service.domain.report import build_report


def _reasoned_with_finding() -> dict:
    return {
        "correlation_id": "stroke-1",
        "findings": [
            {
                "finding_id": "F::KG-A:v1",
                "what": "head falling outside off",
                "why": "weight staying back",
                "impact": {"statement": "LBW risk"},
                "drill": {"name": "closed-shoulder drill"},
                "citation": {"rule_id": "KG-A", "version": 1},
                "confidence": 0.85,
                "provenance": "measured",
            }
        ],
    }


class TestBuildEvidence:
    def test_one_chunk_per_finding_cited_by_rule(self) -> None:
        report = build_report(reasoned=_reasoned_with_finding(), biomechanics={})
        evidence = build_evidence(findings=report.findings, legend_view=report.legend_view)
        assert len(evidence) == 1
        assert evidence[0].citation == "KG-A@v1"
        assert "head falling outside off" in evidence[0].text
        assert "LBW risk" in evidence[0].text
        assert "closed-shoulder drill" in evidence[0].text
        assert evidence[0].confidence == 0.85

    def test_falls_back_to_finding_id_when_no_rule_citation(self) -> None:
        reasoned = {
            "correlation_id": "stroke-1",
            "findings": [{"finding_id": "F::raw", "what": "x", "confidence": 0.5}],
        }
        report = build_report(reasoned=reasoned, biomechanics={})
        evidence = build_evidence(findings=report.findings, legend_view=report.legend_view)
        assert evidence[0].citation == "F::raw"

    def test_no_findings_is_no_evidence(self) -> None:
        report = build_report(
            reasoned={"correlation_id": "stroke-1", "findings": []}, biomechanics={}
        )
        assert build_evidence(findings=report.findings, legend_view=report.legend_view) == []

    def test_legend_styles_become_citable_chunks(self) -> None:
        legend_comparison = {
            "styles": [
                {
                    "style_label": "cover-drive-style-A",
                    "similarity": 72.0,
                    "driving_gaps": [{"metric_id": "BM-01", "description": "later backlift"}],
                    "confidence": 0.8,
                }
            ]
        }
        report = build_report(
            reasoned={"correlation_id": "stroke-1", "findings": []},
            biomechanics={},
            legend_comparison=legend_comparison,
        )
        evidence = build_evidence(findings=report.findings, legend_view=report.legend_view)
        assert len(evidence) == 1
        assert evidence[0].citation == "cover-drive-style-A"
        assert "later backlift" in evidence[0].text
        assert evidence[0].provenance == "modelled"
