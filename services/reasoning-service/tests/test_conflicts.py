"""Conflict resolution via M12 precedence (M13 Step 4, §5, AC-M13-04)."""

from __future__ import annotations

from reasoning_service.domain.conflicts import resolve_conflicts
from reasoning_service.domain.engine import FiredRule


def _fired(rule_id: str) -> FiredRule:
    return FiredRule(
        rule_id=rule_id,
        version=1,
        rule_confidence=0.9,
        fault="f",
        cause="c",
        risk={},
        drill={},
        evidence={},
    )


class TestResolveConflicts:
    def test_precedence_suppresses_the_loser(self) -> None:
        fired = [_fired("KG-A"), _fired("KG-B")]
        conflicts = [
            {"rule_a": "KG-A", "rule_b": "KG-B", "precedence": "KG-A", "note": "A wins on full"}
        ]
        result = resolve_conflicts(fired, conflicts)
        assert [f.rule_id for f in result.surviving] == ["KG-A"]
        assert result.resolutions[0].winner_rule_id == "KG-A"
        assert result.resolutions[0].loser_rule_id == "KG-B"
        assert result.resolutions[0].resolved is True
        assert result.resolutions[0].reason == "A wins on full"

    def test_precedence_for_b_suppresses_a(self) -> None:
        fired = [_fired("KG-A"), _fired("KG-B")]
        conflicts = [{"rule_a": "KG-A", "rule_b": "KG-B", "precedence": "KG-B"}]
        result = resolve_conflicts(fired, conflicts)
        assert [f.rule_id for f in result.surviving] == ["KG-B"]

    def test_unresolved_conflict_keeps_both_and_flags(self) -> None:
        fired = [_fired("KG-A"), _fired("KG-B")]
        conflicts = [{"rule_a": "KG-A", "rule_b": "KG-B", "precedence": None}]
        result = resolve_conflicts(fired, conflicts)
        assert {f.rule_id for f in result.surviving} == {"KG-A", "KG-B"}
        assert result.resolutions[0].resolved is False

    def test_conflict_ignored_when_one_rule_did_not_fire(self) -> None:
        fired = [_fired("KG-A")]  # KG-B not fired
        conflicts = [{"rule_a": "KG-A", "rule_b": "KG-B", "precedence": "KG-B"}]
        result = resolve_conflicts(fired, conflicts)
        assert [f.rule_id for f in result.surviving] == ["KG-A"]
        assert result.resolutions == []

    def test_no_conflicts_keeps_all(self) -> None:
        fired = [_fired("KG-A"), _fired("KG-B")]
        result = resolve_conflicts(fired, [])
        assert len(result.surviving) == 2 and result.resolutions == []
