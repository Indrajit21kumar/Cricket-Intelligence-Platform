"""Subscription repository (used from Step 3 onward).

subscriptions is tenant-scoped (RLS), so all reads/writes happen inside a
:func:`cip_data.tenant_session` bound to the subscription's tenant. The
billing *subject* is always a tenant — individuals have a personal tenant
(Book 2 §5.2) — so ``subject_ref`` is ``"tenant:<uuid>"``.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import BadRequest

ACTIVE_STATUSES = ("trialing", "active", "past_due")


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
