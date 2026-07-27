"""Fact-pattern matcher (M12 Step 5, §11, AC-M12-04).

Pure matching logic: a rule fires only when EVERY condition is satisfied, a
missing fact never fires a rule, and directions/shot/context conditions all
evaluate correctly. Best-confidence-first ordering.
"""

from __future__ import annotations

from typing import Any

from knowledge_service.domain.matcher import MatchFacts, rule_matches, select_matches
from knowledge_service.domain.rule_schema import WORKED_EXAMPLE, validate_rule

# The worked example's conditions: BM-17 > 50 AND BM-01 direction outside_off.
_CONDITIONS = [c.to_dict() for c in validate_rule(WORKED_EXAMPLE).conditions]


class TestRuleMatches:
    def test_fires_when_all_conditions_hold(self) -> None:
        facts = MatchFacts(metrics={"BM-17": 60.0}, directions={"BM-01": "outside_off"})
        assert rule_matches(_CONDITIONS, facts) is True

    def test_does_not_fire_when_one_condition_fails(self) -> None:
        # Plant on time (BM-17 below threshold) -> the rule must not fire.
        facts = MatchFacts(metrics={"BM-17": 20.0}, directions={"BM-01": "outside_off"})
        assert rule_matches(_CONDITIONS, facts) is False

    def test_a_missing_fact_never_fires(self) -> None:
        # BM-01 direction absent -> conservative: no match.
        facts = MatchFacts(metrics={"BM-17": 60.0})
        assert rule_matches(_CONDITIONS, facts) is False

    def test_empty_conditions_never_fire(self) -> None:
        assert rule_matches([], MatchFacts(metrics={"BM-17": 99.0})) is False

    def test_shot_and_context_conditions(self) -> None:
        conds: list[dict[str, Any]] = [
            {"kind": "shot", "op": "eq", "value": "cover_drive"},
            {"kind": "context", "field": "delivery", "op": "in", "value": ["full", "yorker"]},
        ]
        assert rule_matches(conds, MatchFacts(shot="cover_drive", context={"delivery": "full"}))
        assert not rule_matches(conds, MatchFacts(shot="pull", context={"delivery": "full"}))


class TestSelectMatches:
    def _released(
        self, rule_id: str, conditions: list[dict[str, Any]], conf: float
    ) -> dict[str, Any]:
        return {
            "rule_id": rule_id,
            "version": 1,
            "snapshot": {
                "conditions": conditions,
                "confidence": conf,
                "fault": "f",
                "risk": {},
                "drill": {},
            },
        }

    def test_returns_matches_best_confidence_first(self) -> None:
        facts = MatchFacts(metrics={"BM-17": 60.0}, directions={"BM-01": "outside_off"})
        released = [
            self._released("KG-A", _CONDITIONS, 0.7),
            self._released("KG-B", _CONDITIONS, 0.95),
            self._released("KG-C", [{"kind": "shot", "op": "eq", "value": "pull"}], 0.99),
        ]
        matched = select_matches(released, facts)
        assert [m.rule_id for m in matched] == ["KG-B", "KG-A"]  # KG-C didn't fire

    def test_payload_parsing_ignores_non_numeric_metrics(self) -> None:
        facts = MatchFacts.from_payload(
            {"metrics": {"BM-17": 60, "junk": "x"}, "directions": {"BM-01": "outside_off"}}
        )
        assert facts.metrics == {"BM-17": 60.0}
        assert rule_matches(_CONDITIONS, facts) is True
