"""Canonical rule schema validation (M12 Step 2, §5, AC-M12-01).

Proves a well-formed Fault->Cause->Risk->Drill rule loads (the worked example),
and that every kind of malformation is REJECTED rather than half-stored.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from knowledge_service.domain.lifecycle import STATUS_DRAFT
from knowledge_service.domain.rule_schema import (
    WORKED_EXAMPLE,
    RuleValidationError,
    validate_rule,
)


class TestWorkedExample:
    def test_kg_risk_002_loads(self) -> None:
        """AC-M12-01: the spec's worked example validates end to end."""
        rule = validate_rule(WORKED_EXAMPLE)
        assert rule.rule_id == "KG-RISK-002"
        assert rule.fault == "head falling outside off"
        assert rule.cause == "weight staying back"
        assert rule.risk.magnitude == "+~25%"
        assert rule.drill.objective  # a measurable objective is present
        assert rule.confidence == 0.91
        assert rule.status == STATUS_DRAFT
        assert len(rule.conditions) == 2

    def test_round_trips_to_dict(self) -> None:
        rule = validate_rule(WORKED_EXAMPLE)
        again = validate_rule(rule.to_dict())
        assert again.to_dict() == rule.to_dict()


def _valid() -> dict[str, Any]:
    return copy.deepcopy(WORKED_EXAMPLE)


class TestRejections:
    def test_bad_rule_id_is_rejected(self) -> None:
        bad = _valid()
        bad["rule_id"] = "not a rule id"
        with pytest.raises(RuleValidationError, match="rule_id"):
            validate_rule(bad)

    def test_empty_conditions_is_rejected(self) -> None:
        bad = _valid()
        bad["conditions"] = []
        with pytest.raises(RuleValidationError, match="conditions"):
            validate_rule(bad)

    def test_confidence_out_of_range_is_rejected(self) -> None:
        bad = _valid()
        bad["confidence"] = 1.4
        with pytest.raises(RuleValidationError, match="confidence"):
            validate_rule(bad)

    def test_missing_fault_is_rejected(self) -> None:
        bad = _valid()
        del bad["fault"]
        with pytest.raises(RuleValidationError, match="fault"):
            validate_rule(bad)

    def test_risk_without_statement_is_rejected(self) -> None:
        bad = _valid()
        bad["risk"] = {"context": "x"}
        with pytest.raises(RuleValidationError, match=r"risk\.statement"):
            validate_rule(bad)

    def test_drill_without_measurable_objective_is_rejected(self) -> None:
        bad = _valid()
        bad["drill"] = {"name": "some drill"}
        with pytest.raises(RuleValidationError, match="objective"):
            validate_rule(bad)

    def test_a_non_metric_id_in_a_metric_condition_is_rejected(self) -> None:
        bad = _valid()
        bad["conditions"] = [{"kind": "metric", "field": "elbow", "op": ">", "value": 1}]
        with pytest.raises(RuleValidationError, match="metric id"):
            validate_rule(bad)

    def test_a_numeric_op_without_a_number_is_rejected(self) -> None:
        bad = _valid()
        bad["conditions"] = [{"kind": "metric", "field": "BM-17", "op": ">", "value": "late"}]
        with pytest.raises(RuleValidationError, match="numeric"):
            validate_rule(bad)
