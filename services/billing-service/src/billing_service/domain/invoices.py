"""Invoice repository (M03 Step 6, FR-M03-05, NFR-M03-04).

Invoices are the immutable, reconcilable record of what the payment provider
did. Every insert is anchored on ``provider_ref`` (UNIQUE per the Step 1
schema) so a replayed webhook can never double-record — the row is created
once and left alone.

Money is expressed only in minor units (paise), never floats — NFR-M03-04
insists on reconcilability against the provider's ledger, and integer maths
is the only way to keep that lossless.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def record_invoice(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    subscription_id: uuid.UUID,
    amount_minor: int,
    currency: str,
    status: str,
    provider_ref: str,
    issued_at: datetime,
) -> tuple[dict[str, Any], bool]:
    """Record an invoice; returns ``(row, inserted)``.

    ``inserted`` is False when the ``provider_ref`` was already stored —
    the row is unchanged, which is exactly the replay-safety guarantee
    AC-M03-04 needs.
    """
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO invoices "
                    "  (id, tenant_id, subscription_id, amount_minor, currency, "
                    "   status, provider_ref, issued_at) "
                    "VALUES (:id, :tid, :sub, :amt, :cur, :st, :pref, :issued) "
                    "ON CONFLICT (provider_ref) DO NOTHING "
                    "RETURNING id, tenant_id, subscription_id, amount_minor, currency, "
                    "          status, provider_ref, issued_at"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "sub": subscription_id,
                    "amt": amount_minor,
                    "cur": currency,
                    "st": status,
                    "pref": provider_ref,
                    "issued": issued_at,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is not None:
        return dict(row), True

    # Replay — fetch the existing row so the caller can log/return it.
    existing = (
        (
            await session.execute(
                text(
                    "SELECT id, tenant_id, subscription_id, amount_minor, currency, "
                    "       status, provider_ref, issued_at "
                    "FROM invoices WHERE provider_ref = :pref"
                ),
                {"pref": provider_ref},
            )
        )
        .mappings()
        .one()
    )
    return dict(existing), False


async def list_invoices_for_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return every invoice for the current tenant (session already RLS-bound)."""
    _ = tenant_id  # session is already bound to it via RLS
    rows = await session.execute(
        text(
            "SELECT id, tenant_id, subscription_id, amount_minor, currency, "
            "       status, provider_ref, issued_at "
            "FROM invoices ORDER BY issued_at DESC"
        )
    )
    return [dict(r) for r in rows.mappings()]
