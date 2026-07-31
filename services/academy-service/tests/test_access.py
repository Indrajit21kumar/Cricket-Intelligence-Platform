"""Coach visibility scoping (M18 Step 7, FR-M18-06/07, AC-M18-02/06)."""

from __future__ import annotations

import uuid

from academy_service.domain.access import can_coach_view_player
from academy_service.domain.sources import RosterMember
from cip_core.roles import COACH, PLAYER


def _player(person_id: uuid.UUID) -> RosterMember:
    return RosterMember(person_id=person_id, role=PLAYER, display_name="Player")


class TestCanCoachViewPlayer:
    def test_assigned_current_member_is_visible(self) -> None:
        player_id = uuid.uuid4()
        assert (
            can_coach_view_player(
                roster=[_player(player_id)], player_id=player_id, is_assigned=True
            )
            is True
        )

    def test_unassigned_member_is_not_visible(self) -> None:
        player_id = uuid.uuid4()
        assert (
            can_coach_view_player(
                roster=[_player(player_id)], player_id=player_id, is_assigned=False
            )
            is False
        )

    def test_assigned_but_no_longer_a_member_is_not_visible(self) -> None:
        """Portability (FR-M18-07): a stale assignment never grants access alone."""
        player_id = uuid.uuid4()
        assert can_coach_view_player(roster=[], player_id=player_id, is_assigned=True) is False

    def test_a_coach_role_member_who_is_not_a_player_still_counts_as_a_member(self) -> None:
        person_id = uuid.uuid4()
        member = RosterMember(person_id=person_id, role=COACH, display_name="Coach")
        assert can_coach_view_player(roster=[member], player_id=person_id, is_assigned=True) is True

    def test_empty_roster_and_no_assignment_is_not_visible(self) -> None:
        assert can_coach_view_player(roster=[], player_id=uuid.uuid4(), is_assigned=False) is False
