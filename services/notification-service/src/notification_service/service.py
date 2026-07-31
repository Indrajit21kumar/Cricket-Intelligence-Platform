"""Notification application service (M19 Steps 5-7).

Where every prior step's pure domain logic meets I/O: map the event
(Step 2), check contactability/consent + gate on preferences/quiet hours
(Step 4), idempotently create the notification row (Step 5), render +
dispatch the message (Step 3), and record the delivery attempt's outcome
under the retry/dead-letter policy (Step 5). Step 6 adds the inbox,
preference updates, and provider delivery-status handling on top. Step 7
audits every attempt of a TRANSACTIONAL send (FR-M19-08) — the
verification/security/billing category §5 names as sensitive, not a
notion invented here.

A gated-out or unresolvable send is never persisted at all — the
``notifications`` table is "one row per send intent" (§9), and a send
that was refused before dispatch was never a genuine intent. A
re-delivered event that already produced a row is recognised via the
idempotency key and returned as-is, never re-dispatched (FR-M19-07).
Opt-out is immediate by construction, not a separate mechanism: Step 4's
preference read happens fresh on every send, never cached, so the very
next event after a PATCH /v1/preferences opt-out is already gated out.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import audit_record, contactability, verified_guardians_of
from cip_data import admin_session
from notification_service.domain import delivery_attempts_repo, notifications_repo
from notification_service.domain.channels import EmailChannel, InAppChannel, PushChannel, dispatch
from notification_service.domain.event_mapping import (
    TRANSACTIONAL,
    UnmappedEventError,
    map_event,
    notification_type_by_key,
)
from notification_service.domain.gating import PreferenceRecord, QuietHours, gate_send
from notification_service.domain.preferences_repo import get_preference, upsert_preference
from notification_service.domain.retry import evaluate_attempt
from notification_service.domain.templates import render_message


def _preference_record(row: dict[str, Any] | None) -> PreferenceRecord | None:
    if row is None:
        return None
    quiet_hours = None
    raw_quiet_hours = row.get("quiet_hours")
    if isinstance(raw_quiet_hours, dict):
        start = raw_quiet_hours.get("start_hour")
        end = raw_quiet_hours.get("end_hour")
        if isinstance(start, int) and isinstance(end, int):
            quiet_hours = QuietHours(start_hour=start, end_hour=end)
    return PreferenceRecord(enabled=bool(row["enabled"]), quiet_hours=quiet_hours)


async def _attempt_delivery(
    *,
    session_factory: async_sessionmaker[Any],
    notification_id: uuid.UUID,
    recipient_ref: uuid.UUID,
    channel: str,
    message: Any,
    email_channel: EmailChannel,
    push_channel: PushChannel,
    in_app_channel: InAppChannel,
    is_sensitive: bool = False,
) -> str:
    """Dispatch one attempt, record it, and update the notification's status.

    Shared by :func:`send_notification` (attempt 1) and
    :func:`retry_notification` (attempt 2+) — the policy and bookkeeping
    are identical either way, only where the recipient/message came from
    differs. ``is_sensitive`` audits this attempt (FR-M19-08) — every
    attempt of a TRANSACTIONAL send, not just its first or its final
    outcome, since each one is itself a sensitive action (a security/
    billing message actually going out, or failing to).
    """
    async with admin_session(session_factory) as session:
        attempt_number = (
            await delivery_attempts_repo.count_attempts(session, notification_id=notification_id)
            + 1
        )

    # The retry/DLQ boundary: any provider failure becomes a retryable
    # attempt (Step 5's own concern), never an unhandled crash.
    provider_ref: str | None = None
    succeeded = True
    try:
        provider_ref = await dispatch(
            channel=channel,
            recipient_ref=recipient_ref,
            message=message,
            email_channel=email_channel,
            push_channel=push_channel,
            in_app_channel=in_app_channel,
        )
    except Exception:
        succeeded = False

    outcome = evaluate_attempt(succeeded=succeeded, attempt_number=attempt_number)

    async with admin_session(session_factory) as session:
        await delivery_attempts_repo.record_attempt(
            session,
            notification_id=notification_id,
            attempt=attempt_number,
            status=outcome.attempt_status,
            provider_ref=provider_ref,
        )
        await notifications_repo.update_status(
            session, notification_id=notification_id, status=outcome.notification_status
        )
        if is_sensitive:
            await audit_record(
                session,
                action=f"notification.{outcome.notification_status}",
                entity=f"person:{recipient_ref}",
                actor="notification-service",
                meta={
                    "notification_id": str(notification_id),
                    "channel": channel,
                    "attempt": attempt_number,
                },
                tenant_id=None,
            )
    return outcome.notification_status


async def send_notification(
    *,
    session_factory: async_sessionmaker[Any],
    topic: str,
    payload: Mapping[str, Any],
    event_ref: str,
    channel: str,
    email_channel: EmailChannel,
    push_channel: PushChannel,
    in_app_channel: InAppChannel,
    hour: int | None = None,
) -> dict[str, Any] | None:
    """Send (or idempotently no-op, or refuse) one notification for one channel.

    Returns the notification row on completion (sent/failed/dead_lettered),
    the existing row when this (event, recipient, channel) was already
    handled, or ``None`` when the event has no resolvable recipient yet or
    the send was gated out before ever becoming an intent.
    """
    try:
        mapped = map_event(topic=topic, payload=payload, event_ref=event_ref)
    except UnmappedEventError:
        return None
    if mapped.recipient_ref is None:
        return None

    # Keyed on the EVENT INSTANCE (event_ref), not the topic: two distinct
    # report.ready events for the same person (two different analysis
    # sessions) must both be sendable. Only a re-delivery of the SAME
    # event_ref (e.g. a Kafka redelivery after a consumer crash) collides.
    idempotency_key = f"{event_ref}:{mapped.recipient_ref}:{channel}"
    async with admin_session(session_factory) as session:
        existing = await notifications_repo.get_by_idempotency_key(
            session, idempotency_key=idempotency_key
        )
    if existing is not None:
        return existing

    async with admin_session(session_factory) as session:
        info = await contactability(session, person_id=mapped.recipient_ref)
        guardians = (
            await verified_guardians_of(session, minor_person_id=mapped.recipient_ref)
            if info.is_minor
            else []
        )
        preference_row = await get_preference(
            session,
            person_ref=mapped.recipient_ref,
            channel=channel,
            topic=mapped.notification_type.key,
        )

    effective_hour = hour if hour is not None else datetime.now(UTC).hour
    decision = gate_send(
        category=mapped.notification_type.category,
        recipient_ref=mapped.recipient_ref,
        is_contactable=info.is_contactable,
        is_minor=info.is_minor,
        guardian_refs=guardians,
        preference=_preference_record(preference_row),
        hour=effective_hour,
    )
    if not decision.allowed or decision.effective_recipient_ref is None:
        return None
    effective_recipient: uuid.UUID = decision.effective_recipient_ref

    async with admin_session(session_factory) as session:
        row = await notifications_repo.create_if_new(
            session,
            recipient_ref=effective_recipient,
            notification_type=mapped.notification_type.key,
            channel=channel,
            event_ref=event_ref,
            idempotency_key=idempotency_key,
        )
    if row is None:
        # Lost a race with another delivery of the same event.
        async with admin_session(session_factory) as session:
            return await notifications_repo.get_by_idempotency_key(
                session, idempotency_key=idempotency_key
            )

    message = render_message(mapped.notification_type, payload)
    status = await _attempt_delivery(
        session_factory=session_factory,
        notification_id=row["id"],
        recipient_ref=effective_recipient,
        channel=channel,
        message=message,
        email_channel=email_channel,
        push_channel=push_channel,
        in_app_channel=in_app_channel,
        is_sensitive=mapped.notification_type.category == TRANSACTIONAL,
    )
    return {**row, "status": status}


async def retry_notification(
    *,
    session_factory: async_sessionmaker[Any],
    notification_id: uuid.UUID,
    recipient_ref: uuid.UUID,
    notification_type_key: str,
    channel: str,
    payload: Mapping[str, Any],
    email_channel: EmailChannel,
    push_channel: PushChannel,
    in_app_channel: InAppChannel,
) -> str:
    """Re-attempt a notification that previously failed (FR-M19-06).

    A future retry worker selects which "failed" rows are due for another
    attempt and calls this per row — the same attempt/status bookkeeping
    :func:`send_notification` uses, not a duplicate policy. Not idempotency
    -gated: the caller already knows this is the SAME notification being
    retried, not a fresh event that might be a re-delivery.
    """
    notification_type = notification_type_by_key(notification_type_key)
    message = render_message(notification_type, payload)
    return await _attempt_delivery(
        session_factory=session_factory,
        notification_id=notification_id,
        recipient_ref=recipient_ref,
        channel=channel,
        message=message,
        email_channel=email_channel,
        push_channel=push_channel,
        in_app_channel=in_app_channel,
        is_sensitive=notification_type.category == TRANSACTIONAL,
    )


async def get_inbox(
    *,
    session_factory: async_sessionmaker[Any],
    recipient_ref: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """A recipient's own in-app inbox (§10, AC-M19-01's rendering half)."""
    async with admin_session(session_factory) as session:
        return await notifications_repo.list_for_recipient(
            session, recipient_ref=recipient_ref, channel="in_app", limit=limit, offset=offset
        )


async def mark_notification_read(
    *,
    session_factory: async_sessionmaker[Any],
    notification_id: uuid.UUID,
    recipient_ref: uuid.UUID,
) -> bool:
    """Mark one in-app notification read, scoped to its own recipient."""
    async with admin_session(session_factory) as session:
        return await notifications_repo.mark_read(
            session, notification_id=notification_id, recipient_ref=recipient_ref
        )


async def update_preference(
    *,
    session_factory: async_sessionmaker[Any],
    person_ref: uuid.UUID,
    channel: str,
    topic: str,
    enabled: bool,
    quiet_hours: dict[str, Any] | None,
) -> dict[str, Any]:
    """Update one (channel, topic) preference (§10's ``PATCH /v1/preferences``)."""
    async with admin_session(session_factory) as session:
        return await upsert_preference(
            session,
            person_ref=person_ref,
            channel=channel,
            topic=topic,
            enabled=enabled,
            quiet_hours=quiet_hours,
        )


async def handle_provider_status(
    *,
    session_factory: async_sessionmaker[Any],
    provider_ref: str,
    delivered: bool,
) -> dict[str, Any] | None:
    """Apply a channel provider's async delivery confirmation (§10's status webhook).

    Distinct from :func:`_attempt_delivery`'s own retry/dead-letter policy:
    this reflects what the PROVIDER reports about a send we already made,
    not another attempt of our own — a bounce here doesn't consume one of
    :data:`~notification_service.domain.retry.MAX_DELIVERY_ATTEMPTS`, it's
    just recorded and the notification marked failed. Returns None for an
    unrecognised provider_ref (a webhook for a send this service never made).
    """
    async with admin_session(session_factory) as session:
        notification = await notifications_repo.find_by_provider_ref(
            session, provider_ref=provider_ref
        )
        if notification is None:
            return None
        status = "delivered" if delivered else "failed"
        await notifications_repo.update_status(
            session, notification_id=notification["id"], status=status
        )
        await delivery_attempts_repo.record_attempt(
            session,
            notification_id=notification["id"],
            attempt=await delivery_attempts_repo.count_attempts(
                session, notification_id=notification["id"]
            )
            + 1,
            status="success" if delivered else "failure",
            provider_ref=provider_ref,
        )
        if notification_type_by_key(notification["type"]).category == TRANSACTIONAL:
            await audit_record(
                session,
                action=f"notification.{status}",
                entity=f"person:{notification['recipient_ref']}",
                actor="notification-service",
                meta={"notification_id": str(notification["id"]), "provider_ref": provider_ref},
                tenant_id=None,
            )
    return {**notification, "status": status}
