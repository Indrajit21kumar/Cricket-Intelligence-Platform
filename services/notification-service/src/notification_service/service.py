"""Notification application service (M19 Step 5).

Where every prior step's pure domain logic meets I/O: map the event
(Step 2), check contactability/consent + gate on preferences/quiet hours
(Step 4), idempotently create the notification row (Step 5), render +
dispatch the message (Step 3), and record the delivery attempt's outcome
under the retry/dead-letter policy (Step 5).

A gated-out or unresolvable send is never persisted at all — the
``notifications`` table is "one row per send intent" (§9), and a send
that was refused before dispatch was never a genuine intent. A
re-delivered event that already produced a row is recognised via the
idempotency key and returned as-is, never re-dispatched (FR-M19-07).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_core import contactability, verified_guardians_of
from cip_data import admin_session
from notification_service.domain import delivery_attempts_repo, notifications_repo
from notification_service.domain.channels import EmailChannel, InAppChannel, PushChannel, dispatch
from notification_service.domain.event_mapping import (
    UnmappedEventError,
    map_event,
    notification_type_by_key,
)
from notification_service.domain.gating import PreferenceRecord, QuietHours, gate_send
from notification_service.domain.preferences_repo import get_preference
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
) -> str:
    """Dispatch one attempt, record it, and update the notification's status.

    Shared by :func:`send_notification` (attempt 1) and
    :func:`retry_notification` (attempt 2+) — the policy and bookkeeping
    are identical either way, only where the recipient/message came from
    differs.
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

    idempotency_key = f"{topic}:{mapped.recipient_ref}:{channel}"
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
    )
