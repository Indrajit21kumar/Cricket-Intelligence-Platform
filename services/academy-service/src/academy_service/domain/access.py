"""Coach visibility scoping (M18 Step 7, FR-M18-06, FR-M18-07, NFR-M18-02, AC-M18-02/06).

One reusable rule, composed from two independent facts:

1. ``is_assigned`` — M18's own ``coach_assignments`` row is active for
   this (coach, player) pair in this tenant (a repo lookup).
2. The player is a CURRENT M02 member of the tenant — Step 2's
   :func:`~academy_service.domain.roster.is_roster_member`, re-run
   against a freshly-loaded roster rather than trusted from a cached
   assignment.

Re-checking (2) on every read, rather than only at assignment time, is
what makes portability (FR-M18-07) automatic: the moment a player's M02
membership ends, this check starts failing for every coach who had
access, with no action needed on ``coach_assignments`` (soft, never
deleted — Step 1's migration already establishes that a stale row never
grants access on its own). The player's own M04 profile is never touched
by any of this — M18 holds no copy of it to revoke.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from academy_service.domain.roster import is_roster_member
from academy_service.domain.sources import RosterMember


def can_coach_view_player(
    *,
    roster: Sequence[RosterMember],
    player_id: uuid.UUID,
    is_assigned: bool,
) -> bool:
    """Whether a coach may view this player's dashboard/sessions/analytics row.

    Both facts must hold: an active assignment AND current tenant
    membership. Either alone is insufficient — an assignment to someone
    who has since left grants nothing, and mere tenant membership without
    an assignment doesn't either (FR-M18-06: assigned players only).
    """
    return is_assigned and is_roster_member(roster, person_id=player_id)
