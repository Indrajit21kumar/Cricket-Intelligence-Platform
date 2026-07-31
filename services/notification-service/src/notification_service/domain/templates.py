"""Message templating (M19 Step 3, FR-M19-02).

Renders a subject/body pair from a :class:`~notification_service.domain.
event_mapping.NotificationType` and the source event's own payload — never
free-generated content, always a fixed template filled from fields the
producer already published. A field the template wants but the payload
lacks renders as an honest placeholder-free fallback (the sentence just
omits that clause) rather than a raised error or a "None" leaking into
the text.

``dna_updated``'s spec framing (§4: "(Digest) progress update") describes
a FUTURE batching capability (§14 lists "Digest batching" as a future
enhancement, not one of the 7 v1 steps) — this template renders an
immediate single-update message, the honest v1 behaviour, not a digest
that doesn't exist yet.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from notification_service.domain.event_mapping import (
    BILLING_PAYMENT_FAILED,
    BILLING_PAYMENT_RECOVERED,
    BILLING_PAYMENT_SUSPENDED,
    DNA_UPDATED,
    PLAN_UPDATED,
    REPORT_READY,
    SESSION_SCHEDULED,
    NotificationType,
)


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    """A rendered subject/body pair, ready to hand to a channel adapter."""

    subject: str
    body: str


class UnknownTemplateError(ValueError):
    """Raised when a notification type has no registered template."""


def _report_ready(payload: Mapping[str, Any]) -> RenderedMessage:
    return RenderedMessage(
        subject="Your batting analysis is ready",
        body="Your batting analysis is ready to view.",
    )


def _plan_updated(payload: Mapping[str, Any]) -> RenderedMessage:
    stage = payload.get("stage")
    stage_clause = f" ({stage} stage)" if isinstance(stage, str) else ""
    return RenderedMessage(
        subject="Your new training plan is available",
        body=f"Your new training plan{stage_clause} is available.",
    )


def _dna_updated(payload: Mapping[str, Any]) -> RenderedMessage:
    return RenderedMessage(
        subject="Your Cricket DNA was updated",
        body="Your Cricket DNA profile was just updated with your latest session.",
    )


def _session_scheduled(payload: Mapping[str, Any]) -> RenderedMessage:
    scheduled_at = payload.get("scheduled_at")
    when_clause = f" for {scheduled_at}" if isinstance(scheduled_at, str) else ""
    return RenderedMessage(
        subject="Session scheduled",
        body=f"A new training session has been scheduled{when_clause}.",
    )


def _billing_payment_failed(payload: Mapping[str, Any]) -> RenderedMessage:
    attempt = payload.get("attempt_number")
    attempt_clause = f" (attempt {attempt})" if isinstance(attempt, int) else ""
    return RenderedMessage(
        subject="We couldn't process your payment",
        body=f"We couldn't process your subscription payment{attempt_clause}. "
        "We'll retry automatically.",
    )


def _billing_payment_suspended(payload: Mapping[str, Any]) -> RenderedMessage:
    return RenderedMessage(
        subject="Your subscription has been suspended",
        body="Your subscription has been suspended after repeated failed payments.",
    )


def _billing_payment_recovered(payload: Mapping[str, Any]) -> RenderedMessage:
    return RenderedMessage(
        subject="Payment received",
        body="Your payment was successful — your subscription is active again.",
    )


_TEMPLATES: dict[str, Callable[[Mapping[str, Any]], RenderedMessage]] = {
    REPORT_READY.key: _report_ready,
    PLAN_UPDATED.key: _plan_updated,
    DNA_UPDATED.key: _dna_updated,
    SESSION_SCHEDULED.key: _session_scheduled,
    BILLING_PAYMENT_FAILED.key: _billing_payment_failed,
    BILLING_PAYMENT_SUSPENDED.key: _billing_payment_suspended,
    BILLING_PAYMENT_RECOVERED.key: _billing_payment_recovered,
}


def render_message(
    notification_type: NotificationType, payload: Mapping[str, Any]
) -> RenderedMessage:
    """Render the subject/body for this notification type from its event payload."""
    renderer = _TEMPLATES.get(notification_type.key)
    if renderer is None:
        raise UnknownTemplateError(f"no template for notification type: {notification_type.key!r}")
    return renderer(payload)
