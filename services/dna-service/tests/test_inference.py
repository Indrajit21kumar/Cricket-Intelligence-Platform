"""Strengths/weak_areas inference from recurring evidence (M16 Step 5, FR-M16-05)."""

from __future__ import annotations

from dna_service.domain.inference import (
    RECURRENCE_THRESHOLD,
    RecurrenceState,
    infer_strengths,
    infer_weak_areas,
)


def _finding(rule_id: str) -> dict:
    return {"citation": {"rule_id": rule_id, "version": 1}}


def _position(metric_id: str, classification: str) -> dict:
    return {"metric_id": metric_id, "classification": classification}


class TestRecurrenceState:
    def test_round_trips_through_json(self) -> None:
        state = RecurrenceState(counts={"KG-A": 2, "KG-B": 1})
        restored = RecurrenceState.from_json(state.to_json())
        assert dict(restored.counts) == {"KG-A": 2, "KG-B": 1}

    def test_empty_or_none_prior_value_is_a_fresh_state(self) -> None:
        assert dict(RecurrenceState.from_json(None).counts) == {}
        assert dict(RecurrenceState.from_json("").counts) == {}

    def test_malformed_json_does_not_crash_and_yields_a_fresh_state(self) -> None:
        assert dict(RecurrenceState.from_json("{not valid json").counts) == {}

    def test_non_dict_json_yields_a_fresh_state(self) -> None:
        assert dict(RecurrenceState.from_json("[1, 2, 3]").counts) == {}

    def test_increment_adds_new_keys_and_bumps_existing_ones(self) -> None:
        state = RecurrenceState(counts={"KG-A": 1})
        updated = state.increment(["KG-A", "KG-B"])
        assert dict(updated.counts) == {"KG-A": 2, "KG-B": 1}

    def test_recurring_only_returns_keys_at_or_above_threshold(self) -> None:
        state = RecurrenceState(
            counts={"KG-A": RECURRENCE_THRESHOLD, "KG-B": RECURRENCE_THRESHOLD - 1}
        )
        assert state.recurring() == ["KG-A"]


class TestInferWeakAreas:
    def test_a_finding_seen_once_does_not_recur_yet(self) -> None:
        result = infer_weak_areas(prior_value=None, findings=[_finding("KG-A")])
        assert result.recurring == ()

    def test_a_finding_seen_across_two_sessions_recurs(self) -> None:
        first = infer_weak_areas(prior_value=None, findings=[_finding("KG-A")])
        second = infer_weak_areas(prior_value=first.stored_value, findings=[_finding("KG-A")])
        assert second.recurring == ("KG-A",)

    def test_distinct_rule_ids_are_tracked_independently(self) -> None:
        first = infer_weak_areas(prior_value=None, findings=[_finding("KG-A")])
        second = infer_weak_areas(prior_value=first.stored_value, findings=[_finding("KG-B")])
        assert second.recurring == ()  # neither has recurred twice yet

    def test_a_finding_with_no_rule_citation_is_ignored(self) -> None:
        result = infer_weak_areas(prior_value=None, findings=[{"finding_id": "F::raw"}])
        assert result.recurring == ()

    def test_no_findings_leaves_state_unchanged(self) -> None:
        first = infer_weak_areas(prior_value=None, findings=[_finding("KG-A")])
        second = infer_weak_areas(prior_value=first.stored_value, findings=[])
        assert second.stored_value == first.stored_value


class TestInferStrengths:
    def test_a_within_metric_seen_across_two_sessions_recurs(self) -> None:
        first = infer_strengths(prior_value=None, benchmark_position=[_position("BM-01", "within")])
        second = infer_strengths(
            prior_value=first.stored_value, benchmark_position=[_position("BM-01", "within")]
        )
        assert second.recurring == ("BM-01",)

    def test_an_outside_classification_is_never_counted_as_a_strength(self) -> None:
        first = infer_strengths(
            prior_value=None, benchmark_position=[_position("BM-01", "outside")]
        )
        second = infer_strengths(
            prior_value=first.stored_value, benchmark_position=[_position("BM-01", "outside")]
        )
        assert second.recurring == ()

    def test_no_benchmark_position_leaves_state_unchanged(self) -> None:
        first = infer_strengths(prior_value=None, benchmark_position=[_position("BM-01", "within")])
        second = infer_strengths(prior_value=first.stored_value, benchmark_position=[])
        assert second.stored_value == first.stored_value
