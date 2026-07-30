"""Confidence combination + trust propagation (M13 Step 5, §5, FR-M13-04/07)."""

from __future__ import annotations

from reasoning_service.domain.confidence import (
    PROVENANCE_ESTIMATED,
    PROVENANCE_MEASURED,
    combine_confidence,
    combined_provenance,
    is_provisional,
)
from reasoning_service.domain.facts import Fact


def _fact(
    mid: str, conf: float, *, provenance: str = "measured", provisional: bool = False
) -> Fact:
    return Fact(
        metric_id=mid, value=1.0, confidence=conf, provenance=provenance, provisional=provisional
    )


class TestCombineConfidence:
    def test_rule_times_weakest_metric(self) -> None:
        triggering = [_fact("BM-17", 0.75), _fact("PH-06", 0.66)]
        # 0.9 * min(0.75, 0.66) = 0.594.
        assert combine_confidence(0.9, triggering) == 0.594

    def test_no_triggering_metrics_uses_rule_confidence(self) -> None:
        assert combine_confidence(0.8, []) == 0.8

    def test_missing_rule_confidence_uses_metric(self) -> None:
        assert combine_confidence(None, [_fact("BM-01", 0.7)]) == 0.7


class TestProvisional:
    def test_provisional_when_a_triggering_fact_is(self) -> None:
        triggering = [_fact("BM-17", 0.75), _fact("PH-06", 0.66, provisional=True)]
        assert is_provisional(triggering, report_provisional=False) is True

    def test_provisional_when_the_report_is(self) -> None:
        assert is_provisional([_fact("BM-01", 0.9)], report_provisional=True) is True

    def test_not_provisional_when_clean(self) -> None:
        assert is_provisional([_fact("BM-01", 0.9)], report_provisional=False) is False


class TestProvenance:
    def test_estimated_when_any_fact_estimated(self) -> None:
        triggering = [_fact("BM-01", 0.9), _fact("PH-06", 0.66, provenance="estimated")]
        assert combined_provenance(triggering) == PROVENANCE_ESTIMATED

    def test_measured_when_all_measured(self) -> None:
        assert (
            combined_provenance([_fact("BM-01", 0.9), _fact("BM-17", 0.8)]) == PROVENANCE_MEASURED
        )

    def test_measured_default_when_no_triggering(self) -> None:
        assert combined_provenance([]) == PROVENANCE_MEASURED
