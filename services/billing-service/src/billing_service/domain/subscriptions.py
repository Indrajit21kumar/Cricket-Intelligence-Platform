"""Subscription repository (used from Step 3 onward).

subscriptions is tenant-scoped (RLS), so all reads/writes happen inside a
:func:`cip_data.tenant_session` bound to the subscription's tenant. The
billing *subject* is always a tenant — individuals have a personal tenant
(Book 2 §5.2) — so ``subject_ref`` is ``"tenant:<uuid>"``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import BadRequest

ACTIVE_STATUSES = ("trialing", "active", "past_due")

# Billing-period lengths (Book 2 §5.2: monthly plans; trials are shorter).
DEFAULT_PERIOD_DAYS = 30
TRIAL_PERIOD_DAYS = 14


def tenant_from_subject(subject: str) -> uuid.UUID:
    """Parse ``"tenant:<uuid>"`` -> UUID, else raise BadRequest.

    M03 subjects are tenants (an individual uses their personal tenant).
    """
    prefix, _, rest = subject.partition(":")
    if prefix != "tenant":
        raise BadRequest("subject must be of the form 'tenant:<uuid>'")
    try:
        return uuid.UUID(rest)
    except ValueError as exc:
        raise BadRequest("subject tenant id is not a valid UUID") from exc


async def get_active_subscription(
    session: AsyncSession, tenant_id: uuid.UUID
) -> dict[str, Any] | None:
    """Return the tenant's current (non-canceled/suspended) subscription."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, tenant_id, subject_ref, plan_id, status, "
                    "       period_start, period_end, provider_ref "
                    "FROM subscriptions "
                    "WHERE status = ANY(:statuses) "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"statuses": list(ACTIVE_STATUSES)},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def get_subscription(
    session: AsyncSession, subscription_id: uuid.UUID
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, tenant_id, subject_ref, plan_id, status, "
                    "       period_start, period_end, provider_ref "
                    "FROM subscriptions WHERE id = :id"
                ),
                {"id": subscription_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


# --- Lifecycle (M03 Step 5, FR-M03-02) ---------------------------------------
#
# All three writes run inside a tenant_session bound to the subscription's
# tenant, so RLS WITH CHECK validates tenant_id == the session GUC. The caller
# is responsible for invalidating the entitlement cache after a plan/status
# change (routes do this) so the fast-path check re-resolves the new plan.


async def create_subscription(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subject_ref: str,
    plan_id: uuid.UUID,
    trialing: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Start a subscription for a tenant. Returns the created row.

    ``trialing`` starts a shorter free trial period (status ``trialing``);
    otherwise the subscription is immediately ``active``.
    """
    now = now or datetime.now(UTC)
    status = "trialing" if trialing else "active"
    period_days = TRIAL_PERIOD_DAYS if trialing else DEFAULT_PERIOD_DAYS
    sub_id = uuid.uuid4()
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO subscriptions "
                    "  (id, tenant_id, subject_ref, plan_id, status, "
                    "   period_start, period_end) "
                    "VALUES (:id, :tid, :subj, :plan, :status, :start, :end) "
                    "RETURNING id, tenant_id, subject_ref, plan_id, status, "
                    "          period_start, period_end, provider_ref"
                ),
                {
                    "id": sub_id,
                    "tid": tenant_id,
                    "subj": subject_ref,
                    "plan": plan_id,
                    "status": status,
                    "start": now,
                    "end": now + timedelta(days=period_days),
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def change_plan(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
    new_plan_id: uuid.UUID,
) -> dict[str, Any]:
    """Point a subscription at a new plan (upgrade/downgrade).

    The billing period is unchanged — proration settles the price difference
    for the remainder of the current period (see
    :func:`billing_service.domain.proration.compute_proration`).
    """
    row = (
        (
            await session.execute(
                text(
                    "UPDATE subscriptions "
                    "SET plan_id = :plan, updated_at = now() "
                    "WHERE id = :id "
                    "RETURNING id, tenant_id, subject_ref, plan_id, status, "
                    "          period_start, period_end, provider_ref"
                ),
                {"plan": new_plan_id, "id": subscription_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def cancel_subscription(
    session: AsyncSession,
    *,
    subscription_id: uuid.UUID,
) -> dict[str, Any]:
    """Cancel a subscription (terminal state ``canceled``)."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE subscriptions "
                    "SET status = 'canceled', updated_at = now() "
                    "WHERE id = :id "
                    "RETURNING id, tenant_id, subject_ref, plan_id, status, "
                    "          period_start, period_end, provider_ref"
                ),
                {"id": subscription_id},
            )
        )
        .mappings()
        .one()
    )
    return dict(row)
