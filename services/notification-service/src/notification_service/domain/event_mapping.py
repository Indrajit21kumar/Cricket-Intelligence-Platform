"""Platform event -> notification type mapping (M19 Step 2, FR-M19-01, AC-M19-01).

Maps ONLY the events real producers in this codebase actually publish:
``report.ready`` (M14), ``dna.updated`` (M16), ``plan.updated`` (M17),
``session.scheduled`` (M18), and ``billing.notification.requested`` (M03's
dunning loop — which already anticipated M19: its own docstring reads
"M19 (not yet built) subscribes and does the actual send").

M02 identity events (verification, password reset) are deliberately OUT of
this mapping: identity-service sends those synchronously today (a property
of a security-sensitive flow, not an oversight — confirmed by reading its
actual code, no ``event_bus``/``EventEnvelope`` reference exists anywhere
in identity-service). Routing them through M19's async retry/DLQ pipeline
would be a real architecture change to an already-shipped, security-facing
module — out of scope for "map an event that exists."

Most topics carry ONE notification type. ``billing.notification.requested``
is the exception: M03's dunning loop reuses one topic for three distinct
templates (payment_failed/suspended/recovered), carried in the payload's
own ``template`` field — that field IS the notification type key for this
topic, not something invented here.

Recipient extraction is per-topic: M14/M16/M17's payloads carry
``person_id`` directly; M18's ``session.scheduled`` carries ``coach_ref``
(the session's assigned coach). Billing's payload carries neither — only
``subscription_id`` — so its recipient cannot be resolved from the event
alone; ``MappedNotification.recipient_ref`` is ``None`` for it until a
later step adds a subscription->person resolver (the same "adapter added
only when a concrete step needs it" pattern as M17's ``TenantResolver``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

TRANSACTIONAL = "transactional"
ENGAGEMENT = "engagement"


@dataclass(frozen=True, slots=True)
class NotificationType:
    """A notification type this platform can produce."""

    key: str
    category: str  # TRANSACTIONAL | ENGAGEMENT


@dataclass(frozen=True, slots=True)
class MappedNotification:
    """One platform event, resolved to what M19 should notify about."""

    notification_type: NotificationType
    recipient_ref: uuid.UUID | None
    event_ref: str


class UnmappedEventError(ValueError):
    """Raised when an event's topic/template isn't one M19 knows how to notify about."""


def _parse_uuid(raw: object) -> uuid.UUID | None:
    if not isinstance(raw, str):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def _person_id(payload: Mapping[str, Any]) -> uuid.UUID | None:
    return _parse_uuid(payload.get("person_id"))


def _coach_ref(payload: Mapping[str, Any]) -> uuid.UUID | None:
    return _parse_uuid(payload.get("coach_ref"))


def _no_recipient(payload: Mapping[str, Any]) -> uuid.UUID | None:
    return None


REPORT_READY = NotificationType(key="report_ready", category=ENGAGEMENT)
DNA_UPDATED = NotificationType(key="dna_updated", category=ENGAGEMENT)
PLAN_UPDATED = NotificationType(key="plan_updated", category=ENGAGEMENT)
SESSION_SCHEDULED = NotificationType(key="session_scheduled", category=ENGAGEMENT)
BILLING_PAYMENT_FAILED = NotificationType(key="billing.payment_failed", category=TRANSACTIONAL)
BILLING_PAYMENT_SUSPENDED = NotificationType(
    key="billing.payment_suspended", category=TRANSACTIONAL
)
BILLING_PAYMENT_RECOVERED = NotificationType(
    key="billing.payment_recovered", category=TRANSACTIONAL
)

_BILLING_TOPIC = "billing.notification.requested"
_BILLING_TEMPLATES: dict[str, NotificationType] = {
    BILLING_PAYMENT_FAILED.key: BILLING_PAYMENT_FAILED,
    BILLING_PAYMENT_SUSPENDED.key: BILLING_PAYMENT_SUSPENDED,
    BILLING_PAYMENT_RECOVERED.key: BILLING_PAYMENT_RECOVERED,
}

#: Every known notification type, keyed by its own key — the reverse of
#: mapping a topic to a type, used to look a type back up from a
#: persisted ``notifications.type`` value (e.g. when retrying a row that
#: already exists, rather than re-deriving it from a fresh event).
ALL_NOTIFICATION_TYPES: dict[str, NotificationType] = {
    t.key: t
    for t in (
        REPORT_READY,
        DNA_UPDATED,
        PLAN_UPDATED,
        SESSION_SCHEDULED,
        BILLING_PAYMENT_FAILED,
        BILLING_PAYMENT_SUSPENDED,
        BILLING_PAYMENT_RECOVERED,
    )
}


def notification_type_by_key(key: str) -> NotificationType:
    """The :class:`NotificationType` for an already-known key.

    Raises :class:`UnmappedEventError` for a key nothing produces — the
    same refuse-don't-guess posture as :func:`map_event`.
    """
    notification_type = ALL_NOTIFICATION_TYPES.get(key)
    if notification_type is None:
        raise UnmappedEventError(f"no notification type registered for key: {key!r}")
    return notification_type


_RecipientExtractor = Callable[[Mapping[str, Any]], "uuid.UUID | None"]
_FIXED_TOPICS: dict[str, tuple[NotificationType, _RecipientExtractor]] = {
    "report.ready": (REPORT_READY, _person_id),
    "dna.updated": (DNA_UPDATED, _person_id),
    "plan.updated": (PLAN_UPDATED, _person_id),
    "session.scheduled": (SESSION_SCHEDULED, _coach_ref),
}


def map_event(*, topic: str, payload: Mapping[str, Any], event_ref: str) -> MappedNotification:
    """Resolve one platform event to a notification type + recipient.

    Raises :class:`UnmappedEventError` for any topic (or, for billing,
    template) M19 doesn't recognise — an unrecognised event is refused,
    never guessed into some default type.
    """
    if topic == _BILLING_TOPIC:
        template = payload.get("template")
        notification_type = _BILLING_TEMPLATES.get(template) if isinstance(template, str) else None
        if notification_type is None:
            raise UnmappedEventError(f"unrecognised billing template: {template!r}")
        return MappedNotification(
            notification_type=notification_type,
            recipient_ref=_no_recipient(payload),
            event_ref=event_ref,
        )

    mapped = _FIXED_TOPICS.get(topic)
    if mapped is None:
        raise UnmappedEventError(f"no notification mapping for topic: {topic!r}")
    notification_type, extract_recipient = mapped
    return MappedNotification(
        notification_type=notification_type,
        recipient_ref=extract_recipient(payload),
        event_ref=event_ref,
    )
