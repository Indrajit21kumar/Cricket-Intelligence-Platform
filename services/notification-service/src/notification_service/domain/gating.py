"""Send gating — preferences, quiet hours, consent/contactability (M19 Step 4).

FR-M19-03 (honour per-user channel/topic preferences and quiet hours),
FR-M19-04 (send only to consented, contactable recipients; guardian-mediated
for minors), AC-M19-02/03.

Pure decision function: the caller (a later wiring step) gathers the facts
— :class:`~cip_core.ContactabilityInfo`, a minor's verified guardians
(:func:`cip_core.verified_guardians_of`), and the recipient's own
:class:`PreferenceRecord` for this (channel, topic) — and this module just
decides, the same "pure function over pre-gathered facts" shape used
throughout this platform (e.g. M18's ``evaluate_share``).

Two independent gates, in order:

1. Contactability + minors. Not contactable -> refused outright. A minor is
   never contacted directly — guardian-mediated (Book 0 §11.1): the send
   redirects to their first verified guardian, or is refused if they have
   none recorded (never a guess at who to contact instead).
2. Category + preference. TRANSACTIONAL messages are non-optional (FR-M19-05)
   and bypass both the opt-in check and quiet hours — a security/billing
   message still needs to land during someone's quiet hours. ENGAGEMENT
   messages are strictly opt-in: no preference row, or an explicit
   ``enabled=False``, both mean "don't send" (deny by default) — and are
   additionally suppressed during quiet hours.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

TRANSACTIONAL = "transactional"
ENGAGEMENT = "engagement"


@dataclass(frozen=True, slots=True)
class QuietHours:
    """A user's quiet-hours window, in local hours [0, 24)."""

    start_hour: int
    end_hour: int


@dataclass(frozen=True, slots=True)
class PreferenceRecord:
    """One (channel, topic) preference row."""

    enabled: bool
    quiet_hours: QuietHours | None


@dataclass(frozen=True, slots=True)
class GateDecision:
    """Whether a send may proceed, and who it should actually go to."""

    allowed: bool
    reason: str
    effective_recipient_ref: uuid.UUID | None = None


def is_quiet_now(quiet_hours: QuietHours | None, *, hour: int) -> bool:
    """Whether ``hour`` (0-23) falls inside this quiet-hours window."""
    if quiet_hours is None:
        return False
    start, end = quiet_hours.start_hour, quiet_hours.end_hour
    if start == end:
        return False  # degenerate window (e.g. unset) = no quiet hours
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps midnight, e.g. 22 -> 7


def gate_send(
    *,
    category: str,
    recipient_ref: uuid.UUID,
    is_contactable: bool,
    is_minor: bool,
    guardian_refs: Sequence[uuid.UUID],
    preference: PreferenceRecord | None,
    hour: int,
) -> GateDecision:
    """Decide whether a notification may be sent, and to whom."""
    if not is_contactable:
        return GateDecision(allowed=False, reason="not_contactable")

    effective_recipient = recipient_ref
    if is_minor:
        if not guardian_refs:
            return GateDecision(allowed=False, reason="minor_no_guardian")
        effective_recipient = guardian_refs[0]

    if category == TRANSACTIONAL:
        return GateDecision(
            allowed=True, reason="transactional", effective_recipient_ref=effective_recipient
        )

    if preference is None or not preference.enabled:
        return GateDecision(allowed=False, reason="not_opted_in")

    if is_quiet_now(preference.quiet_hours, hour=hour):
        return GateDecision(allowed=False, reason="quiet_hours")

    return GateDecision(
        allowed=True, reason="opted_in", effective_recipient_ref=effective_recipient
    )
