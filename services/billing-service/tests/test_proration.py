"""Unit tests for proration math (M03 Step 5, FR-M03-06).

Pure function, no DB / no Redis / no lifespan — proration is trivially
testable, so this covers the arithmetic (typical, boundary, degenerate)
before the integration tests exercise it end-to-end.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from billing_service.domain.proration import compute_proration


class TestProrationTypical:
    """A 30-day period, cross-checked against the fraction remaining."""

    def test_midcycle_upgrade_net_positive(self) -> None:
        # Starter (0) -> Pro (49900 paise). Halfway through the period the
        # customer owes ~half the Pro price and gets no credit (Starter is free).
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=0,
            new_price_minor=49_900,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start + timedelta(days=15),
        )
        assert p.credit_minor == 0
        # 49900 * (15 days / 30 days) = 24950 (exact — floor division agrees)
        assert p.charge_minor == 24_950
        assert p.net_minor == 24_950
        assert 0.49 < p.fraction_remaining < 0.51

    def test_midcycle_downgrade_net_negative(self) -> None:
        # Pro (49900) -> Starter (0). At halfway the customer is owed the
        # unused half of Pro; no forward charge (Starter is free).
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=0,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start + timedelta(days=15),
        )
        assert p.credit_minor == 24_950
        assert p.charge_minor == 0
        assert p.net_minor == -24_950

    def test_upgrade_between_paid_plans(self) -> None:
        # Pro (49900) -> Academy (999900) at 10 days in (2/3 of the period left).
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start + timedelta(days=10),
        )
        # 20 days / 30 days remaining => 2/3.
        # credit = 49900*20//30 = 33266; charge = 999900*20//30 = 666600
        assert p.credit_minor == 33_266
        assert p.charge_minor == 666_600
        assert p.net_minor == 666_600 - 33_266


class TestProrationBoundaries:
    def test_at_period_start_full_credit_and_charge(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start,
        )
        # Whole period remains -> full old credit, full new charge.
        assert p.credit_minor == 49_900
        assert p.charge_minor == 999_900
        assert p.fraction_remaining == pytest.approx(1.0)

    def test_at_period_end_zero_everything(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=30)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=start,
            period_end=end,
            at=end,
        )
        assert p.credit_minor == 0
        assert p.charge_minor == 0
        assert p.net_minor == 0
        assert p.fraction_remaining == pytest.approx(0.0)

    def test_at_after_period_end_clamps_to_zero(self) -> None:
        """A late-arriving change is treated as end-of-period, not negative."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=30)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=start,
            period_end=end,
            at=end + timedelta(days=5),
        )
        assert p.credit_minor == 0
        assert p.charge_minor == 0
        assert p.fraction_remaining == pytest.approx(0.0)

    def test_at_before_period_start_clamps_to_full(self) -> None:
        """Clock-skew safety — an early ``at`` still bills the full remainder."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        end = start + timedelta(days=30)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=start,
            period_end=end,
            at=start - timedelta(days=2),
        )
        assert p.credit_minor == 49_900
        assert p.charge_minor == 999_900
        assert p.fraction_remaining == pytest.approx(1.0)


class TestProrationDegenerate:
    def test_zero_length_period_returns_zero(self) -> None:
        """A degenerate period never charges (guards against div-by-zero)."""
        moment = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=999_900,
            period_start=moment,
            period_end=moment,
            at=moment,
        )
        assert p.credit_minor == 0
        assert p.charge_minor == 0
        assert p.net_minor == 0
        assert p.fraction_remaining == 0.0

    def test_same_plan_yields_zero_net(self) -> None:
        """Downgrade to the same price is a no-op cost — credit == charge."""
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=49_900,
            new_price_minor=49_900,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start + timedelta(days=7),
        )
        assert p.credit_minor == p.charge_minor
        assert p.net_minor == 0

    def test_free_to_free_is_zero(self) -> None:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        p = compute_proration(
            old_price_minor=0,
            new_price_minor=0,
            period_start=start,
            period_end=start + timedelta(days=30),
            at=start + timedelta(days=10),
        )
        assert p.credit_minor == 0
        assert p.charge_minor == 0
        assert p.net_minor == 0
