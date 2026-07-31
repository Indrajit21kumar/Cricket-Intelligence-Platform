"""Roster composition + coach assignment validation (M18 Step 2, FR-M18-01, AC-M18-01).

The roster's ground truth is M02 membership (:class:`~academy_service.domain.sources.RosterSource`)
— M18 never invents a player. Composing the roster means joining that
membership list with this service's own ``coach_assignments``, so a coach
can see who is in the academy AND who they're currently assigned to.

Assignment validation is a single, structural rule: a coach can only be
assigned to a PLAYER who is an actual current member of the tenant — never
an arbitrary UUID.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from academy_service.domain.sources import RosterMember
from cip_core.roles import PLAYER


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """One player on the roster, with their currently-assigned coaches."""

    person_id: uuid.UUID
    display_name: str | None
    assigned_coaches: tuple[uuid.UUID, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "person_id": str(self.person_id),
            "display_name": self.display_name,
            "assigned_coaches": [str(coach) for coach in self.assigned_coaches],
        }


def compose_roster(
    members: Sequence[RosterMember], assignments: Mapping[uuid.UUID, Sequence[uuid.UUID]]
) -> list[RosterEntry]:
    """The academy's PLAYER roster, each with their active coach assignments.

    ``assignments`` maps player_ref -> the coach_refs currently assigned to
    them (active rows only — the caller filters).
    """
    return [
        RosterEntry(
            person_id=member.person_id,
            display_name=member.display_name,
            assigned_coaches=tuple(assignments.get(member.person_id, ())),
        )
        for member in members
        if member.role == PLAYER
    ]


def is_roster_member(members: Sequence[RosterMember], *, person_id: uuid.UUID) -> bool:
    """Whether ``person_id`` is a current member of this tenant (any role).

    Used to validate a coach assignment: a coach can only be assigned to a
    player who is genuinely a member of the academy right now.
    """
    return any(member.person_id == person_id for member in members)
