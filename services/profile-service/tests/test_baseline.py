"""Unit tests for personal-baseline summary math (M04 Step 5, AC-M04-05).

Pure function — no DB. Typical / boundary / degenerate.
"""

from __future__ import annotations

import pytest

from profile_service.domain.baseline import compute_summary, is_valid_metric_id


class TestComputeSummary:
    def test_empty_is_all_none_count_zero(self) -> None:
        s = compute_summary([])
        assert s["count"] == 0
        assert s["mean"] is None
        assert s["p50"] is None

    def test_single_sample_degenerate(self) -> None:
        s = compute_summary([7.0])
        assert s["count"] == 1
        assert s["mean"] == 7.0
        assert s["stddev"] == 0.0
        assert s["min"] == s["max"] == 7.0
        assert s["p25"] == s["p50"] == s["p75"] == 7.0

    def test_typical_distribution(self) -> None:
        s = compute_summary([2.0, 4.0, 6.0, 8.0])
        assert s["count"] == 4
        assert s["mean"] == pytest.approx(5.0)
        assert s["min"] == 2.0
        assert s["max"] == 8.0
        # Inclusive quartiles of [2,4,6,8]: p50 == median == 5.
        assert s["p50"] == pytest.approx(5.0)
        assert s["p25"] < s["p50"] < s["p75"]

    def test_order_independent(self) -> None:
        a = compute_summary([1.0, 2.0, 3.0, 4.0, 5.0])
        b = compute_summary([5.0, 3.0, 1.0, 4.0, 2.0])
        assert a == b


class TestMetricIdValidation:
    @pytest.mark.parametrize("mid", ["BM-01", "PH-11", "SC-01", "BN-04", "KG-RISK-002"])
    def test_valid_ids(self, mid: str) -> None:
        assert is_valid_metric_id(mid) is True

    @pytest.mark.parametrize("mid", ["bm-01", "BM01", "trait.aggression", "", "1-BM", "B-01"])
    def test_invalid_ids(self, mid: str) -> None:
        assert is_valid_metric_id(mid) is False
