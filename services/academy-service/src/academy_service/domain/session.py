"""Session management + attendance (M18 Step 3, FR-M18-02, AC-M18-03).

Sessions are training events; attendance links a roster player to a
session, with an optional linked analysis (an M05 correlation_id / M14
report ref). Whether a player may be added to a session is Step 2's
``is_roster_member`` rule, reused directly rather than reimplemented — the
same structural check governs both coach assignment and attendance: you
cannot record either for someone who isn't genuinely on the roster.

Status is a small, explicit state machine: SCHEDULED is the only status
that can transition further (to COMPLETED or CANCELLED); both of those are
terminal. This is deliberately conservative — a cancelled session cannot be
un-cancelled, and a completed one cannot be reopened, matching how a real
training calendar behaves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

SCHEDULED = "scheduled"
COMPLETED = "completed"
CANCELLED = "cancelled"

VALID_STATUSES = (SCHEDULED, COMPLETED, CANCELLED)

#: Allowed next statuses per current status — SCHEDULED is the only
#: non-terminal state.
_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    SCHEDULED: (COMPLETED, CANCELLED),
    COMPLETED: (),
    CANCELLED: (),
}


class InvalidSessionTransitionError(ValueError):
    """Raised when a session status change isn't allowed from its current state."""


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """One training session."""

    id: uuid.UUID
    coach_ref: uuid.UUID | None
    scheduled_at: datetime
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "coach_ref": str(self.coach_ref) if self.coach_ref else None,
            "scheduled_at": self.scheduled_at.isoformat(),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class AttendanceRecord:
    """One player's attendance (+ optional linked analysis) for a session."""

    player_ref: uuid.UUID
    attended: bool
    analysis_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_ref": str(self.player_ref),
            "attended": self.attended,
            "analysis_ref": self.analysis_ref,
        }


def can_transition(current_status: str, new_status: str) -> bool:
    return new_status in _ALLOWED_TRANSITIONS.get(current_status, ())


def transition_session(current_status: str, new_status: str) -> str:
    """The new status, or raise if this status change isn't allowed."""
    if new_status not in VALID_STATUSES:
        raise ValueError(f"unknown session status: {new_status!r}")
    if not can_transition(current_status, new_status):
        raise InvalidSessionTransitionError(
            f"cannot transition session from {current_status!r} to {new_status!r}"
        )
    return new_status
