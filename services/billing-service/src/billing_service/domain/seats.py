"""Seats — allocate/deallocate members against a subscription's seat pool
(M03 Step 8, FR-M03-08, AC-M03-06).

Only academy/enterprise plans have seats; Starter/Pro carry a single implicit
seat. The plan's ``seats.max`` entitlement caps the pool size; ``-1`` means
unlimited (currently unused but reserved).

``member_ref`` is an opaque reference to a M02 person id (or membership id,
whichever the caller stored). M03 does not FK to M02 tables — a service
boundary — so we validate only the numeric cap here. UI / API-gateway layers
verify the referenced person actually belongs to the tenant.

Deallocate is a soft state transition (``status='revoked'``) so historical
allocations stay auditable — matches ``billing_audit``'s immutability model.
Reallocating the same ``member_ref`` inserts a new row; the UNIQUE constraint
on (subscription_id, member_ref) means at most one row is 'active' per
member at any time (revoked rows are ignored by count_active_seats).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import BadRequest, Conflict, NotFound


async def count_active_seats(session: AsyncSession, subscription_id: uuid.UUID) -> int:
    row = await session.execute(
        text("SELECT count(*) FROM seats WHERE subscription_id = :sub AND status = 'active'"),
        {"sub": subscription_id},
    )
    return int(row.scalar() or 0)


async def allocate_seat(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    member_ref: str,
    max_seats: int,
) -> dict[str, Any]:
    """Allocate a seat; raises ``Conflict`` when ``seats.max`` is reached.

    ``max_seats`` comes from the plan's ``seats.max`` entitlement. ``-1`` is
    unlimited. ``0`` (default for individual plans) means seats aren't
    supported on this subscription -> BadRequest.
    """
    if max_seats == 0:
        raise BadRequest("This plan does not include seat allocations")

    if max_seats > 0:
        # Count under the current tenant scope (RLS). Race-prone in theory,
        # bounded in practice because a single admin panel drives seat
        # writes; the UNIQUE (subscription_id, member_ref) constraint stops
        # duplicate allocations regardless.
        used = await count_active_seats(session, subscription_id)
        if used >= max_seats:
            raise Conflict(
                "seats.max reached",
                details={"max": max_seats, "used": used},
            )

    seat_id = uuid.uuid4()
    try:
        row = (
            (
                await session.execute(
                    text(
                        "INSERT INTO seats "
                        "  (id, tenant_id, subscription_id, member_ref, status) "
                        "VALUES (:id, :tid, :sub, :ref, 'active') "
                        "RETURNING id, tenant_id, subscription_id, member_ref, status"
                    ),
                    {"id": seat_id, "tid": tenant_id, "sub": subscription_id, "ref": member_ref},
                )
            )
            .mappings()
            .one()
        )
    except Exception as exc:  # pragma: no cover - narrow: UNIQUE violation
        # Same member already has an active seat -> caller sees Conflict.
        raise Conflict(
            "Member already has an active seat on this subscription",
            details={"member_ref": member_ref},
        ) from exc

    return dict(row)


async def deallocate_seat(session: AsyncSession, *, seat_id: uuid.UUID) -> dict[str, Any]:
    """Revoke a seat; 404 if the id doesn't resolve under the RLS scope."""
    row = (
        (
            await session.execute(
                text(
                    "UPDATE seats "
                    "SET status = 'revoked', updated_at = now() "
                    "WHERE id = :id AND status = 'active' "
                    "RETURNING id, tenant_id, subscription_id, member_ref, status"
                ),
                {"id": seat_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise NotFound("Seat not found or already revoked")
    return dict(row)
