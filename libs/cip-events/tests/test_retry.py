"""Unit tests for :mod:`cip_events.retry`."""

from __future__ import annotations

import pytest

from cip_events.retry import RetryPolicy


class TestValidation:
    def test_max_attempts_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RetryPolicy(max_attempts=0)

    def test_initial_delay_must_be_nonneg(self) -> None:
        with pytest.raises(ValueError, match="initial_delay"):
            RetryPolicy(initial_delay_seconds=-1)

    def test_backoff_factor_must_be_gte_one(self) -> None:
        with pytest.raises(ValueError, match="backoff_factor"):
            RetryPolicy(backoff_factor=0.5)

    def test_max_delay_must_be_gte_initial(self) -> None:
        with pytest.raises(ValueError, match="max_delay"):
            RetryPolicy(initial_delay_seconds=10.0, max_delay_seconds=5.0)


class TestDelayForAttempt:
    def test_first_attempt_has_no_delay(self) -> None:
        policy = RetryPolicy()
        assert policy.delay_for_attempt(1) == 0.0

    def test_second_attempt_uses_initial_delay(self) -> None:
        policy = RetryPolicy(initial_delay_seconds=0.5, backoff_factor=2.0)
        assert policy.delay_for_attempt(2) == 0.5

    def test_backoff_doubles(self) -> None:
        policy = RetryPolicy(initial_delay_seconds=0.5, backoff_factor=2.0)
        assert policy.delay_for_attempt(3) == 1.0
        assert policy.delay_for_attempt(4) == 2.0
        assert policy.delay_for_attempt(5) == 4.0

    def test_max_delay_caps(self) -> None:
        policy = RetryPolicy(initial_delay_seconds=1.0, backoff_factor=10.0, max_delay_seconds=5.0)
        # 1.0 -> 10.0 (would exceed), capped to 5.0
        assert policy.delay_for_attempt(3) == 5.0
        assert policy.delay_for_attempt(10) == 5.0

    def test_attempt_zero_rejected(self) -> None:
        with pytest.raises(ValueError, match="attempt"):
            RetryPolicy().delay_for_attempt(0)


class TestShouldRetry:
    def test_more_attempts_available(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(1) is True
        assert policy.should_retry(2) is True

    def test_no_more_after_max(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        assert policy.should_retry(3) is False
        assert policy.should_retry(4) is False
