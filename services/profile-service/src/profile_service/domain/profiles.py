"""Player-profile repository — attributes (M04 Step 2, FR-M04-01/02).

The profile is person-anchored (1:1 with an M02 person) and NOT tenant-owned,
so every query keys on ``person_id`` and runs under
:func:`cip_data.admin_session` (the ``cip_app`` role with no tenant GUC sees
all rows in these no-RLS tables). Consent authorisation happens in the route
layer via the shared cip-core helper *before* we ever touch these rows.

Attributes (height, stance, age band, dominant hand) are declared inputs to
analysis (consumed by M10), not computed outputs, so they carry no provenance
— unlike DNA traits, which do.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class Attributes:
    """The analysis-relevant attribute subset (fast read for M10)."""

    height_cm: int | None
    stance: str | None
    age_band: str | None
    dominant_hand: str | None


async def get_profile_by_person(
    session: AsyncSession, person_id: uuid.UUID
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, person_id, height_cm, stance, age_band, "
                    "       dominant_hand, created_at, updated_at "
                    "FROM player_profiles WHERE person_id = :pid"
                ),
                {"pid": person_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def create_profile(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    height_cm: int | None = None,
    stance: str | None = None,
    age_band: str | None = None,
    dominant_hand: str | None = None,
) -> dict[str, Any]:
    """Create the 1:1 profile for a person. Caller handles the 409 on conflict."""
    profile_id = uuid.uuid4()
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO player_profiles "
                    "  (id, person_id, height_cm, stance, age_band, dominant_hand) "
                    "VALUES (:id, :pid, :h, :st, :ab, :dh) "
                    "RETURNING id, person_id, height_cm, stance, age_band, "
                    "          dominant_hand, created_at, updated_at"
                ),
                {
                    "id": profile_id,
                    "pid": person_id,
                    "h": height_cm,
                    "st": stance,
                    "ab": age_band,
                    "dh": dominant_hand,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


#: The attribute columns a PATCH may set.
_ATTRIBUTE_COLUMNS = ("height_cm", "stance", "age_band", "dominant_hand")


async def update_attributes(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Patch a subset of attributes. ``fields`` holds only the keys to change.

    Uses a static ``COALESCE(:new, col)`` per column so the SQL is fixed (no
    dynamic string building / injection surface). A key absent from ``fields``
    passes NULL and keeps the existing value. As a consequence an attribute
    can't be nulled-out via PATCH — acceptable for these declared inputs.

    Returns the updated row, or None if no profile exists for the person.
    """
    updates = {k: v for k, v in fields.items() if k in _ATTRIBUTE_COLUMNS}
    if not updates:
        # Nothing to change — return the current row unchanged.
        return await get_profile_by_person(session, person_id)

    params: dict[str, Any] = {c: updates.get(c) for c in _ATTRIBUTE_COLUMNS}
    params["pid"] = person_id
    row = (
        (
            await session.execute(
                text(
                    "UPDATE player_profiles SET "
                    "  height_cm = COALESCE(:height_cm, height_cm), "
                    "  stance = COALESCE(:stance, stance), "
                    "  age_band = COALESCE(:age_band, age_band), "
                    "  dominant_hand = COALESCE(:dominant_hand, dominant_hand), "
                    "  updated_at = now() "
                    "WHERE person_id = :pid "
                    "RETURNING id, person_id, height_cm, stance, age_band, "
                    "          dominant_hand, created_at, updated_at"
                ),
                params,
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def get_attributes(session: AsyncSession, person_id: uuid.UUID) -> Attributes | None:
    """Fast read of just the analysis attributes (M10 critical path, <50ms)."""
    row = (
        await session.execute(
            text(
                "SELECT height_cm, stance, age_band, dominant_hand "
                "FROM player_profiles WHERE person_id = :pid"
            ),
            {"pid": person_id},
        )
    ).first()
    if row is None:
        return None
    return Attributes(height_cm=row[0], stance=row[1], age_band=row[2], dominant_hand=row[3])
