"""The generic rule engine (M13 Step 3, §5, FR-M13-02)."""

from __future__ import annotations

from typing import Any

from reasoning_service.domain.engine import fire
from reasoning_service.domain.facts import build_fact_set


def _fact_set() -> Any:
    return build_fact_set(
        biomechanics={
            "correlation_id": "s1",
            "metrics": {
                "BM-01": {"value": 5.0, "provenance": "measured", "confidence": 0.9},
                "BM-17": {"value": 60.0, "provenance": "measured", "confidence": 0.75},
            },
        },
        physics={
            "quantities": {"PH-06": {"value": 42.0, "provenance": "estimated", "confidence": 0.66}}
        },
    )


def _rule(rule_id: str, conditions: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "version": 1,
        "confidence": 0.9,
        "fault": "head falling outside off",
        "cause": "weight staying back",
        "risk": {"statement": "LBW risk"},
        "drill": {"name": "closed-shoulder drill"},
        "evidence": {"tier": 1},
        "conditions": conditions,
        **extra,
    }


class TestFire:
    def test_extracts_triggering_metric_facts(self) -> None:
        rule = _rule(
            "KG-A",
            [
                {"kind": "metric", "field": "BM-17", "op": ">", "value": 50},
                {"kind": "metric", "field": "BM-01", "op": "direction", "value": "outside_off"},
            ],
        )
        fired = fire(_fact_set(), [rule])
        assert len(fired) == 1
        assert set(fired[0].metric_ids) == {"BM-17", "BM-01"}
        assert fired[0].rule_confidence == 0.9
        assert fired[0].evidence == {"tier": 1}

    def test_non_metric_conditions_add_no_triggering_metrics(self) -> None:
        rule = _rule(
            "KG-S",
            [
                {"kind": "shot", "op": "eq", "value": "cover_drive"},
                {"kind": "context", "field": "delivery", "op": "eq", "value": "full"},
            ],
        )
        fired = fire(_fact_set(), [rule])
        assert fired[0].metric_ids == []

    def test_a_condition_metric_absent_from_facts_is_skipped(self) -> None:
        # BM-99 isn't in the fact set (M12 wouldn't have matched it, but be safe).
        rule = _rule("KG-X", [{"kind": "metric", "field": "BM-99", "op": ">", "value": 1}])
        fired = fire(_fact_set(), [rule])
        assert fired[0].metric_ids == []

    def test_fires_one_per_matched_rule(self) -> None:
        rules = [
            _rule("KG-A", [{"kind": "metric", "field": "BM-17", "op": ">", "value": 50}]),
            _rule("KG-B", [{"kind": "metric", "field": "PH-06", "op": ">", "value": 10}]),
        ]
        fired = fire(_fact_set(), rules)
        assert [f.rule_id for f in fired] == ["KG-A", "KG-B"]
        assert fired[1].metric_ids == ["PH-06"]

    def test_no_rules_no_findings(self) -> None:
        assert fire(_fact_set(), []) == []
