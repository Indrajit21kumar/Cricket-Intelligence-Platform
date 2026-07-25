"""Range validation + review routing (M10 Step 6, AC-M10-04).

The invariant under test: out-of-range values are FLAGGED and kept, never
rejected. A coach must be able to see an outlier, and an engineer a possible
formula bug — silently dropping the value hides both.
"""

from __future__ import annotations

from biomechanics_service.domain.catalogue import BM_01, BM_04, BM_06
from biomechanics_service.domain.quality import MetricValue
from biomechanics_service.domain.range_check import check_ranges


def _mv(value: float | None, *, disabled: str | None = None) -> MetricValue:
    return MetricValue(value=value, provenance="measured", confidence=0.9, disabled_reason=disabled)


class TestInRange:
    def test_all_in_range_is_clean(self) -> None:
        # BM-01 head stability range (0, 30); BM-04 x-factor (-20, 80).
        result = check_ranges({BM_01: _mv(5.0), BM_04: _mv(40.0)})
        assert result.out_of_range is False
        assert result.flagged == ()


class TestOutOfRange:
    def test_a_high_value_is_flagged(self) -> None:
        # BM-01 head stability of 60cm is beyond the (0, 30) band.
        result = check_ranges({BM_01: _mv(60.0)})
        assert result.out_of_range is True
        assert BM_01 in result.flagged

    def test_a_low_value_is_flagged(self) -> None:
        # BM-06 knee flexion range (90, 180); 45 is impossibly acute.
        result = check_ranges({BM_06: _mv(45.0)})
        assert result.out_of_range is True
        assert BM_06 in result.flagged

    def test_the_value_is_kept_not_dropped(self) -> None:
        """AC-M10-04: flagged, never silently rejected."""
        metrics = {BM_01: _mv(99.0)}
        result = check_ranges(metrics)
        assert result.out_of_range is True
        # The value survives untouched in the metrics dict.
        assert metrics[BM_01].value == 99.0

    def test_only_the_offending_metric_is_flagged(self) -> None:
        result = check_ranges({BM_01: _mv(60.0), BM_04: _mv(40.0)})
        assert result.flagged == (BM_01,)


class TestSkips:
    def test_a_missing_value_is_not_range_checked(self) -> None:
        result = check_ranges({BM_01: _mv(None)})
        assert result.out_of_range is False

    def test_a_disabled_metric_is_not_range_checked(self) -> None:
        """No value to judge when Step 5 disabled it."""
        result = check_ranges({BM_01: _mv(None, disabled="crease_axis_unresolved")})
        assert result.out_of_range is False


class TestBoundaries:
    def test_exactly_at_the_upper_bound_is_in_range(self) -> None:
        # BM-01 upper bound is 30.0 inclusive.
        assert check_ranges({BM_01: _mv(30.0)}).out_of_range is False

    def test_just_over_the_upper_bound_is_flagged(self) -> None:
        assert check_ranges({BM_01: _mv(30.01)}).out_of_range is True
