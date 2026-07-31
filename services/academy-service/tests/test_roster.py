"""Roster composition + coach assignment validation (M18 Step 2, FR-M18-01, AC-M18-01)."""

from __future__ import annotations

import uuid

from academy_service.domain.roster import compose_roster, is_roster_member
from academy_service.domain.sources import RosterMember
from cip_core.roles import COACH, PLAYER


def _member(role: str = PLAYER, *, name: str | None = "Player One") -> RosterMember:
    return RosterMember(person_id=uuid.uuid4(), role=role, display_name=name)


class TestComposeRoster:
    def test_only_players_appear_on_the_roster(self) -> None:
        player = _member(PLAYER)
        coach = _member(COACH)
        roster = compose_roster([player, coach], {})
        assert [entry.person_id for entry in roster] == [player.person_id]

    def test_no_members_yields_an_empty_roster(self) -> None:
        assert compose_roster([], {}) == []

    def test_a_player_with_no_assignment_has_an_empty_coach_tuple(self) -> None:
        player = _member(PLAYER)
        roster = compose_roster([player], {})
        assert roster[0].assigned_coaches == ()

    def test_a_players_assigned_coaches_are_attached(self) -> None:
        player = _member(PLAYER)
        coach_id = uuid.uuid4()
        roster = compose_roster([player], {player.person_id: [coach_id]})
        assert roster[0].assigned_coaches == (coach_id,)

    def test_display_name_is_carried_through(self) -> None:
        player = _member(PLAYER, name="Kavya")
        roster = compose_roster([player], {})
        assert roster[0].display_name == "Kavya"


class TestIsRosterMember:
    def test_a_current_member_is_recognised(self) -> None:
        player = _member(PLAYER)
        assert is_roster_member([player], person_id=player.person_id) is True

    def test_a_non_member_is_not_recognised(self) -> None:
        player = _member(PLAYER)
        assert is_roster_member([player], person_id=uuid.uuid4()) is False

    def test_empty_roster_recognises_no_one(self) -> None:
        assert is_roster_member([], person_id=uuid.uuid4()) is False

    def test_a_coach_is_still_a_recognised_member_regardless_of_role(self) -> None:
        coach = _member(COACH)
        assert is_roster_member([coach], person_id=coach.person_id) is True
