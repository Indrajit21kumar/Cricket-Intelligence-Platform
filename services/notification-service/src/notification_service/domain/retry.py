"""Retry / dead-letter policy (M19 Step 5, FR-M19-06, NFR-M19-02).

A pure decision over one delivery attempt's outcome and how many attempts
have already been made — the caller (service.py) is the one that actually
retries (re-invokes the send pipeline later) or stops; this module only
says which of the three should happen next.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Attempts allowed before a notification is dead-lettered — an explicit,
#: versioned constant, same practice as M03's dunning RETRY_SCHEDULE_DAYS.
MAX_DELIVERY_ATTEMPTS = 3

SENT = "sent"
FAILED = "failed"
DEAD_LETTERED = "dead_lettered"

SUCCESS = "success"
FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class AttemptOutcome:
    """What this attempt means for the notification and for its own record."""

    notification_status: str  # SENT | FAILED | DEAD_LETTERED
    attempt_status: str  # SUCCESS | FAILURE


def evaluate_attempt(*, succeeded: bool, attempt_number: int) -> AttemptOutcome:
    """Decide the outcome of delivery attempt number ``attempt_number`` (1-based).

    A successful send is always SENT, regardless of how many attempts it
    took. A failure is FAILED (retry later) unless this was the last
    permitted attempt, in which case it's DEAD_LETTERED — permanent,
    no further retry.
    """
    if succeeded:
        return AttemptOutcome(notification_status=SENT, attempt_status=SUCCESS)
    if attempt_number >= MAX_DELIVERY_ATTEMPTS:
        return AttemptOutcome(notification_status=DEAD_LETTERED, attempt_status=FAILURE)
    return AttemptOutcome(notification_status=FAILED, attempt_status=FAILURE)
