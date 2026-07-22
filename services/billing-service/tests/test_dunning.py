"""Unit tests for the dunning schedule (M03 Step 7, AC-M03-05, FR-M03-07).

Pure functions — schedule + terminal check — no DB / no Kafka. The
"process a failed charge and transition the subscription" behaviour is
exercised end-to-end in test_dunning_integration.
"""

from __future__ import annotations

from datetime import UTC, datetime

from billing_service.domain.dunning import (
    MAX_ATTEMPTS,
    RETRY_SCHEDULE_DAYS,
    is_final_failure,
    next_retry_at,
)


class TestSchedule:
    def test_max_attempts_matches_schedule_plus_initial(self) -> None:
        # MAX_ATTEMPTS = 1 initial attempt + N retries.
        assert len(RETRY_SCHEDULE_DAYS) + 1 == MAX_ATTEMPTS

    def test_first_failure_schedules_after_one_day(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        due = next_retry_at(1, now=now)
        assert due is not None
        assert (due - now).days == RETRY_SCHEDULE_DAYS[0]

    def test_each_attempt_uses_its_slot_in_schedule(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)
        for i, gap in enumerate(RETRY_SCHEDULE_DAYS, start=1):
            due = next_retry_at(i, now=now)
            assert due is not None
            assert (due - now).days == gap

    def test_final_attempt_returns_none(self) -> None:
        """When we've hit MAX_ATTEMPTS there's no next retry — we suspend."""
        assert next_retry_at(MAX_ATTEMPTS, now=datetime(2026, 1, 1, tzinfo=UTC)) is None

    def test_is_final_failure_boundary(self) -> None:
        assert is_final_failure(MAX_ATTEMPTS) is True
        assert is_final_failure(MAX_ATTEMPTS - 1) is False
        # Guard against off-by-one at 0 (should never be called with 0, but
        # if it is, don't spuriously suspend).
        assert is_final_failure(0) is False
