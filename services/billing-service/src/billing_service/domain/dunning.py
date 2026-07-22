"""Dunning — recover a failed subscription payment (M03 Step 7, AC-M03-05).

Dunning is the retry-and-notify loop that runs after a charge fails: the
customer's card was declined, the subscription is at risk, and we want to
either recover the payment or gracefully suspend service.

The provider (or a future worker) drives retries — CIP tracks state, tells
M19 to notify at each step, and flips ``subscriptions.status`` to
``suspended`` on the final failure. That "final" line is anchored on the
count of failed invoices for the subscription, so the state machine is
reconcilable end-to-end: attempt N == the N-th ``invoices.status='failed'``
row for that subscription.

State transitions M03 owns::

    active                      -->  past_due       (first charge.failed)
    past_due                    -->  past_due       (retry N failed, N<MAX)
    past_due                    -->  suspended      (final failure, N==MAX)
    past_due                    -->  active         (charge.succeeded)
    suspended                   -->  (terminal via billing; support/ops only)

Notifications:
- Every failed attempt emits a `billing.notification.requested` event to
  Kafka. M19 (not yet built) subscribes and does the actual send. The event
  carries the template + attempt number + next_retry_at so M19 has
  everything without a callback.
- Recovery emits `billing.notification.requested` with a "payment succeeded"
  template.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Retry cadence: attempt 1 immediately (the initial failed webhook), then
# retries after 1/3/7 days. After the 3rd retry attempt fails (i.e. the 4th
# failed invoice), we suspend.
RETRY_SCHEDULE_DAYS: tuple[int, ...] = (1, 3, 7)
MAX_ATTEMPTS = len(RETRY_SCHEDULE_DAYS) + 1  # 4 = initial + 3 retries

# Notification templates M19 will render.
TEMPLATE_PAYMENT_FAILED = "billing.payment_failed"
TEMPLATE_PAYMENT_SUSPENDED = "billing.payment_suspended"
TEMPLATE_PAYMENT_RECOVERED = "billing.payment_recovered"

NOTIFICATION_TOPIC = "billing.notification.requested"


@dataclass(frozen=True, slots=True)
class DunningState:
    """Result of processing a failed charge.

    ``action`` is what the state machine did:
      - "retry_scheduled" — subscription now past_due, next retry pending.
      - "suspended"       — final failure; subscription now suspended.
    """

    action: str
    attempt_number: int
    next_retry_at: datetime | None
    template: str


def next_retry_at(attempt_number: int, *, now: datetime | None = None) -> datetime | None:
    """When the next retry is due, or None if this attempt was the final one.

    ``attempt_number`` is 1-indexed and counts *this* failed attempt.
    So on attempt_number=1 we schedule the 1st retry (1 day out).
    On attempt_number=MAX_ATTEMPTS we return None (no more retries).
    """
    now = now or datetime.now(UTC)
    idx = attempt_number - 1
    if idx >= len(RETRY_SCHEDULE_DAYS):
        return None
    return now + timedelta(days=RETRY_SCHEDULE_DAYS[idx])


def is_final_failure(attempt_number: int) -> bool:
    """True once the subscription has hit ``MAX_ATTEMPTS`` failed charges."""
    return attempt_number >= MAX_ATTEMPTS


async def _count_failed_invoices(session: AsyncSession, subscription_id: uuid.UUID) -> int:
    row = await session.execute(
        text("SELECT count(*) FROM invoices WHERE subscription_id = :sub AND status = 'failed'"),
        {"sub": subscription_id},
    )
    return int(row.scalar() or 0)


async def _set_status(session: AsyncSession, subscription_id: uuid.UUID, status: str) -> None:
    await session.execute(
        text("UPDATE subscriptions SET status = :s, updated_at = now() WHERE id = :id"),
        {"s": status, "id": subscription_id},
    )


async def process_failed_charge(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    now: datetime | None = None,
) -> DunningState:
    """Advance the dunning state machine for a subscription that just had a
    failed invoice recorded. Returns what happened + when the next retry is
    due, so the caller can emit the notification event.

    The failed invoice must already exist (the count is what defines the
    attempt number).
    """
    now = now or datetime.now(UTC)
    attempts = await _count_failed_invoices(session, subscription_id)
    if attempts == 0:
        # Defensive: the caller should record the failed invoice first.
        raise ValueError("process_failed_charge called with 0 failed invoices")

    if is_final_failure(attempts):
        await _set_status(session, subscription_id, "suspended")
        return DunningState(
            action="suspended",
            attempt_number=attempts,
            next_retry_at=None,
            template=TEMPLATE_PAYMENT_SUSPENDED,
        )

    await _set_status(session, subscription_id, "past_due")
    return DunningState(
        action="retry_scheduled",
        attempt_number=attempts,
        next_retry_at=next_retry_at(attempts, now=now),
        template=TEMPLATE_PAYMENT_FAILED,
    )


async def process_successful_charge(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
) -> DunningState | None:
    """Handle a successful charge for a subscription.

    - If the subscription was ``past_due``, this is a recovery: flip it back
      to ``active`` and return a "payment recovered" DunningState so the
      caller emits the recovery notification.
    - If it was already active/trialing, this is a routine renewal — return
      None (no state change, no notification).
    - Suspended subscriptions don't auto-recover on a chance charge; that
      requires an explicit re-subscribe via the lifecycle API.
    """
    row = (
        await session.execute(
            text("SELECT status FROM subscriptions WHERE id = :id"),
            {"id": subscription_id},
        )
    ).first()
    if row is None:
        return None
    status = str(row[0])
    if status != "past_due":
        return None

    await _set_status(session, subscription_id, "active")
    return DunningState(
        action="recovered",
        attempt_number=0,
        next_retry_at=None,
        template=TEMPLATE_PAYMENT_RECOVERED,
    )
