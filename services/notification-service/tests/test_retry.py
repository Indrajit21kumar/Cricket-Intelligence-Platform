"""Retry / dead-letter policy (M19 Step 5, FR-M19-06)."""

from __future__ import annotations

from notification_service.domain.retry import (
    DEAD_LETTERED,
    FAILED,
    FAILURE,
    MAX_DELIVERY_ATTEMPTS,
    SENT,
    SUCCESS,
    evaluate_attempt,
)


class TestEvaluateAttempt:
    def test_a_success_on_the_first_attempt_is_sent(self) -> None:
        outcome = evaluate_attempt(succeeded=True, attempt_number=1)
        assert outcome.notification_status == SENT
        assert outcome.attempt_status == SUCCESS

    def test_a_success_on_a_later_attempt_is_still_sent(self) -> None:
        outcome = evaluate_attempt(succeeded=True, attempt_number=MAX_DELIVERY_ATTEMPTS)
        assert outcome.notification_status == SENT

    def test_a_failure_below_the_attempt_ceiling_is_failed_not_dead_lettered(self) -> None:
        outcome = evaluate_attempt(succeeded=False, attempt_number=MAX_DELIVERY_ATTEMPTS - 1)
        assert outcome.notification_status == FAILED
        assert outcome.attempt_status == FAILURE

    def test_a_failure_at_the_attempt_ceiling_is_dead_lettered(self) -> None:
        outcome = evaluate_attempt(succeeded=False, attempt_number=MAX_DELIVERY_ATTEMPTS)
        assert outcome.notification_status == DEAD_LETTERED
        assert outcome.attempt_status == FAILURE

    def test_a_failure_past_the_ceiling_is_still_dead_lettered(self) -> None:
        outcome = evaluate_attempt(succeeded=False, attempt_number=MAX_DELIVERY_ATTEMPTS + 5)
        assert outcome.notification_status == DEAD_LETTERED
