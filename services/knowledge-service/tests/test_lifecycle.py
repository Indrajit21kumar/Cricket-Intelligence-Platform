"""Rule lifecycle transitions (M12 Step 3, §12)."""

from __future__ import annotations

from knowledge_service.domain.lifecycle import (
    SERVABLE_STATUS,
    STATUS_APPROVED,
    STATUS_DRAFT,
    STATUS_IN_REVIEW,
    STATUS_RELEASED,
    STATUS_SUPERSEDED,
    STATUSES,
    can_transition,
)


class TestTransitions:
    def test_the_happy_path_is_legal(self) -> None:
        assert can_transition(STATUS_DRAFT, STATUS_IN_REVIEW)
        assert can_transition(STATUS_IN_REVIEW, STATUS_APPROVED)
        assert can_transition(STATUS_APPROVED, STATUS_RELEASED)
        assert can_transition(STATUS_RELEASED, STATUS_SUPERSEDED)

    def test_review_can_bounce_back_to_draft(self) -> None:
        assert can_transition(STATUS_IN_REVIEW, STATUS_DRAFT)

    def test_a_draft_cannot_skip_review(self) -> None:
        assert not can_transition(STATUS_DRAFT, STATUS_APPROVED)
        assert not can_transition(STATUS_DRAFT, STATUS_RELEASED)

    def test_superseded_is_terminal(self) -> None:
        for target in STATUSES:
            assert not can_transition(STATUS_SUPERSEDED, target)

    def test_only_released_is_servable(self) -> None:
        assert SERVABLE_STATUS == STATUS_RELEASED

    def test_five_statuses(self) -> None:
        assert len(STATUSES) == 5
