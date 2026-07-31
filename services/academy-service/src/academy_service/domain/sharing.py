"""Report sharing under consent + M19 notify intent (M18 Step 6).

FR-M18-05 (compose shareable training/parent reports from M14/M17),
FR-M18-08 (trigger M19 notifications for report events), AC-M18-07
(sharing respects consent, incl. guardian consent).

A share targets one of two recipient kinds, per §10's "Share a report
(parent/coach), consented":

- ``guardian`` — a parent/guardian report. Governed entirely by
  :func:`cip_core.check_profile_access`'s own "guardian" branch (a
  verified M02 guardianship) — the single source of truth for guardian
  access (Book 0 §11.1), not re-derived here.
- ``coach`` — a training report shared with a coach. Also gated by
  ``check_profile_access``'s "sharing_consent" branch (an active tenant +
  the player's sharing consent), but M18 layers one further, narrower
  rule on top: the coach must be assigned to THIS player specifically
  (FR-M18-06's "a coach sees only assigned players"), not merely any
  coach who shares a tenant with consent.

This module stays pure — it takes an already-computed
:class:`cip_core.AccessDecision` (the caller runs the real M02 check
against a DB session) and M18's own assignment fact, and decides. It also
shapes the :class:`NotificationIntent` M19 should receive, but does not
publish it — that a later step's service-layer wiring does, over the same
``cip_events`` bus every other module already publishes through.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from cip_core import AccessDecision

GUARDIAN = "guardian"
COACH = "coach"
VALID_RECIPIENT_KINDS = (GUARDIAN, COACH)

NOTIFY_TOPIC = "report.shared"


class InvalidRecipientError(ValueError):
    """Raised when a ``shared_with`` string doesn't parse to a known recipient."""


@dataclass(frozen=True, slots=True)
class ShareRecipient:
    """One share recipient, parsed from ``shared_reports.shared_with``."""

    kind: str
    recipient_id: uuid.UUID

    def to_ref(self) -> str:
        return f"{self.kind}:{self.recipient_id}"


def parse_recipient(shared_with: str) -> ShareRecipient:
    """Parse the wire format, e.g. ``"guardian:<uuid>"`` or ``"coach:<uuid>"``."""
    kind, _, raw_id = shared_with.partition(":")
    if kind not in VALID_RECIPIENT_KINDS or not raw_id:
        raise InvalidRecipientError(f"unrecognised share recipient: {shared_with!r}")
    try:
        recipient_id = uuid.UUID(raw_id)
    except ValueError as exc:
        raise InvalidRecipientError(f"unrecognised share recipient: {shared_with!r}") from exc
    return ShareRecipient(kind=kind, recipient_id=recipient_id)


@dataclass(frozen=True, slots=True)
class ShareDecision:
    """Whether a share may proceed, with an auditable reason either way."""

    allowed: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "reason": self.reason}


def evaluate_share(
    *,
    recipient: ShareRecipient,
    access: AccessDecision,
    is_assigned_coach: bool,
) -> ShareDecision:
    """Decide whether this share may proceed.

    ``access`` is M02's own consent/guardianship decision for this
    (subject, recipient) pair — sufficient on its own for a guardian
    recipient. A coach recipient additionally needs ``is_assigned_coach``:
    M18's own narrower assignment rule on top of the broader tenant-level
    sharing consent ``access`` already checked.
    """
    if not access.allowed:
        return ShareDecision(allowed=False, reason=access.reason)
    if recipient.kind == COACH and not is_assigned_coach:
        return ShareDecision(allowed=False, reason="coach_not_assigned")
    return ShareDecision(allowed=True, reason=access.reason)


@dataclass(frozen=True, slots=True)
class NotificationIntent:
    """What M19 should be told about a completed share."""

    topic: str
    tenant_id: uuid.UUID
    player_ref: uuid.UUID
    recipient_ref: str
    report_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "tenant_id": str(self.tenant_id),
            "player_ref": str(self.player_ref),
            "recipient_ref": self.recipient_ref,
            "report_ref": self.report_ref,
        }


def build_notification_intent(
    *,
    tenant_id: uuid.UUID,
    player_ref: uuid.UUID,
    recipient: ShareRecipient,
    report_ref: str,
) -> NotificationIntent:
    """The M19 notification an ALLOWED share should trigger.

    The caller only builds this after :func:`evaluate_share` returns
    ``allowed=True`` — this function itself doesn't re-check that, since
    it has no access to the decision's grounds, only the share's shape.
    """
    return NotificationIntent(
        topic=NOTIFY_TOPIC,
        tenant_id=tenant_id,
        player_ref=player_ref,
        recipient_ref=recipient.to_ref(),
        report_ref=report_ref,
    )
