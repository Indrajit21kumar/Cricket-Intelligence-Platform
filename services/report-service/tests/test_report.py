"""Report assembly from analysis.reasoned + metrics (M14 Step 2, FR-M14-01, AC-M14-01)."""

from __future__ import annotations

from typing import Any

from report_service.domain.narrative import Narrative
from report_service.domain.report import attach_narrative, build_report


def _reasoned() -> dict[str, Any]:
    return {
        "correlation_id": "stroke-1",
        "person_id": "11111111-1111-1111-1111-111111111111",
        "shot_type": "cover_drive",
        "shot_confidence": 0.8,
        "kg_version": "kg@3",
        "findings": [
            {
                "finding_id": "F::KG-A:v1",
                "what": "head falling outside off",
                "why": "weight staying back",
                "impact": {"statement": "LBW risk"},
                "drill": {"name": "closed-shoulder drill"},
                "evidence": [
                    {
                        "metric_id": "BM-01",
                        "value": 5.0,
                        "confidence": 0.9,
                        "provenance": "measured",
                    }
                ],
                "citation": {"rule_id": "KG-A", "version": 1},
                "confidence": 0.85,
                "provenance": "measured",
                "provisional": False,
            }
        ],
        "match_risk": {"provenance": "modelled", "items": []},
        "provisional": False,
    }


def _bio() -> dict[str, Any]:
    return {"metrics": {"BM-01": {"value": 5.0, "provenance": "measured", "confidence": 0.9}}}


class TestBuildReport:
    def test_assembles_scores_findings_and_panels(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        assert report.correlation_id == "stroke-1"
        assert report.kg_version == "kg@3"
        assert len(report.findings) == 1
        assert {p.metric_id for p in report.metric_panels} == {"BM-01"}
        assert report.scores.balance.value == 83.0  # 100 - 20*0.85 (finding confidence)

    def test_carries_shot_context_and_match_risk(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        assert report.shot_type == "cover_drive"
        assert report.match_risk["provenance"] == "modelled"

    def test_video_and_legend_are_none_until_later_steps(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        assert report.annotated_video_ref is None
        assert report.legend_view is None

    def test_to_dict_round_trips_the_structure(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        payload = report.to_dict()
        assert payload["schema_version"] == "report.structure/1.0"
        assert payload["scores"]["overall"]["value"] is not None

    def test_reproducible_same_inputs_same_report(self) -> None:
        """AC-M14-07: same findings + rule version -> same structured claims."""
        a = build_report(reasoned=_reasoned(), biomechanics=_bio()).to_dict()
        b = build_report(reasoned=_reasoned(), biomechanics=_bio()).to_dict()
        assert a == b

    def test_provisional_propagates_from_the_reasoned_payload(self) -> None:
        reasoned = {**_reasoned(), "provisional": True}
        report = build_report(reasoned=reasoned, biomechanics=_bio())
        assert report.provisional is True

    def test_no_findings_is_a_clean_high_scoring_report(self) -> None:
        reasoned = {**_reasoned(), "findings": []}
        report = build_report(reasoned=reasoned, biomechanics=_bio())
        assert report.scores.overall.value == 100.0

    def test_legend_comparison_is_rendered_when_m15_has_produced_one(self) -> None:
        legend_comparison = {
            "styles": [
                {
                    "style_label": "cover-drive-style-A",
                    "similarity": 72.0,
                    "driving_gaps": [
                        {
                            "metric_id": "BM-01",
                            "description": "backlift starts later than the benchmark",
                            "player_value": 12.0,
                            "benchmark_value": 8.0,
                        }
                    ],
                    "confidence": 0.8,
                }
            ],
            "benchmark_version": "cibl@1",
        }
        report = build_report(
            reasoned=_reasoned(), biomechanics=_bio(), legend_comparison=legend_comparison
        )
        assert report.legend_view is not None
        assert report.legend_view["styles"][0]["similarity"] == 72.0
        assert "endorse" in report.legend_view["disclaimer"].lower()

    def test_narrative_is_none_until_attach_narrative_runs(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        assert report.narrative_text is None
        assert report.narrative_citations == ()

    def test_attach_narrative_fills_in_text_and_citations(self) -> None:
        report = build_report(reasoned=_reasoned(), biomechanics=_bio())
        narrative = Narrative(text="head falling outside off [KG-A@v1]", citations=("KG-A@v1",))
        updated = attach_narrative(report, narrative)
        assert updated.narrative_text == narrative.text
        assert updated.narrative_citations == ("KG-A@v1",)
        assert report.narrative_text is None  # original is unchanged (frozen dataclass)
