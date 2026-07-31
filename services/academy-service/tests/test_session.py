"""Session management + attendance (M18 Step 3, FR-M18-02, AC-M18-03)."""

from __future__ import annotations

import pytest

from academy_service.domain.session import (
    CANCELLED,
    COMPLETED,
    SCHEDULED,
    InvalidSessionTransitionError,
    can_transition,
    transition_session,
)


class TestCanTransition:
    def test_scheduled_can_become_completed(self) -> None:
        assert can_transition(SCHEDULED, COMPLETED) is True

    def test_scheduled_can_become_cancelled(self) -> None:
        assert can_transition(SCHEDULED, CANCELLED) is True

    def test_completed_is_terminal(self) -> None:
        assert can_transition(COMPLETED, SCHEDULED) is False
        assert can_transition(COMPLETED, CANCELLED) is False

    def test_cancelled_is_terminal(self) -> None:
        assert can_transition(CANCELLED, SCHEDULED) is False
        assert can_transition(CANCELLED, COMPLETED) is False


class TestTransitionSession:
    def test_valid_transition_returns_the_new_status(self) -> None:
        assert transition_session(SCHEDULED, COMPLETED) == COMPLETED

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(InvalidSessionTransitionError):
            transition_session(COMPLETED, SCHEDULED)

    def test_unknown_status_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown session status"):
            transition_session(SCHEDULED, "not_a_status")

    def test_a_cancelled_session_cannot_be_reopened(self) -> None:
        with pytest.raises(InvalidSessionTransitionError):
            transition_session(CANCELLED, COMPLETED)
