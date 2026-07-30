"""The reasoning pipeline (M13 Step 8, AC-M13-01/03/07)."""

from __future__ import annotations

from typing import Any

from reasoning_service.domain.facts import build_fact_set
from reasoning_service.domain.pipeline import SCHEMA_VERSION, reason


def _fact_set(**overrides: Any) -> Any:
    biomechanics = {
        "correlation_id": "stroke-1",
        "person_id": "11111111-1111-1111-1111-111111111111",
        "shot_type": "cover_drive",
        "shot_confidence": 0.8,
        "phase_boundaries": {"impact": 14},
        "metrics": {
            "BM-01": {"value": 5.0, "provenance": "measured", "confidence": 0.9},
            "BM-17": {"value": 60.0, "provenance": "measured", "confidence": 0.75},
        },
        "provisional": False,
    }
    physics = {
        "quantities": {"PH-06": {"value": 42.0, "provenance": "estimated", "confidence": 0.66}}
    }
    biomechanics.update(overrides)
    return build_fact_set(biomechanics=biomechanics, physics=physics)


def _rule(rule_id: str, **overrides: Any) -> dict[str, Any]:
    rule = {
        "rule_id": rule_id,
        "version": 1,
        "confidence": 0.9,
        "fault": "head falling outside off",
        "cause": "weight staying back",
        "risk": {"statement": "LBW risk", "magnitude": "+~25%"},
        "drill": {"name": "closed-shoulder drill", "objective": "head over knee 8/10"},
        "evidence": {"tier": 1},
        "conditions": [{"kind": "metric", "field": "BM-17", "op": ">", "value": 50}],
    }
    rule.update(overrides)
    return rule


class TestReason:
    def test_ac_m13_01_emits_full_finding(self) -> None:
        """AC-M13-01: findings carry what/why/impact/drill/evidence/confidence."""
        result = reason(_fact_set(), [_rule("KG-A")], kg_version="kg@1")
        assert result.kg_version == "kg@1"
        assert result.schema_version == SCHEMA_VERSION
        finding = result.findings[0].to_dict()
        assert finding["what"] and finding["why"]
        assert finding["impact"] and finding["drill"]
        assert finding["evidence"] and finding["citation"]["rule_id"] == "KG-A"

    def test_ac_m13_03_no_finding_without_a_rule(self) -> None:
        """AC-M13-03: no rules -> no findings (no unsupported advice)."""
        assert reason(_fact_set(), [], kg_version="kg@1").findings == []

    def test_ac_m13_07_deterministic(self) -> None:
        """AC-M13-07: identical facts + rules -> identical findings."""
        a = reason(_fact_set(), [_rule("KG-A")], kg_version="kg@1")
        b = reason(_fact_set(), [_rule("KG-A")], kg_version="kg@1")
        assert a.findings_payload() == b.findings_payload()
        assert a.match_risk_payload() == b.match_risk_payload()

    def test_ac_m13_05_provisional_input_gives_provisional_finding(self) -> None:
        """AC-M13-05: findings on provisional inputs are flagged provisional."""
        result = reason(_fact_set(provisional=True), [_rule("KG-A")], kg_version="kg@1")
        assert result.provisional is True
        assert result.findings[0].provisional is True

    def test_ac_m13_06_match_risk_is_modelled(self) -> None:
        payload = reason(_fact_set(), [_rule("KG-A")], kg_version="kg@1").match_risk_payload()
        assert payload["provenance"] == "modelled"
        assert payload["items"][0]["magnitude"] == "+~25%"

    def test_conflict_precedence_suppresses_loser(self) -> None:
        """AC-M13-04: precedence recorded + suppresses the loser."""
        rules = [_rule("KG-A"), _rule("KG-B")]
        conflicts = [{"rule_a": "KG-A", "rule_b": "KG-B", "precedence": "KG-A"}]
        result = reason(_fact_set(), rules, conflicts=conflicts, kg_version="kg@1")
        assert [f.rule_id for f in result.findings] == ["KG-A"]
        quality = result.quality_payload()
        assert quality["resolutions"][0]["winner"] == "KG-A"
        assert quality["resolutions"][0]["resolved"] is True

    def test_kg_version_pinned_on_result(self) -> None:
        result = reason(_fact_set(), [_rule("KG-A")], kg_version="kg@2026-07-27")
        assert result.kg_version == "kg@2026-07-27"
        assert result.quality_payload()["kg_version"] == "kg@2026-07-27"
