"""Profile export + deletion (M04 Step 6, FR-M04-09).

Data-subject rights over the person-anchored profile:

- **Export** gathers the whole profile — attributes, current DNA, trait
  history, snapshot index, personal baselines, and the history index — into
  one portable bundle.
- **Delete** removes the profile row; every child table (dna_traits,
  dna_trait_history, dna_snapshots, personal_baselines, history_index) is
  ``ON DELETE CASCADE`` to ``player_profiles.id``, so one DELETE erases the
  player's whole record.

Portability (NFR-M04-04): neither of these is tied to a tenant. Because the
profile is person-anchored, leaving/joining a tenant never touches these rows
— only the caller's *access* changes (via the consent + membership check).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from profile_service.domain.baseline import list_baselines
from profile_service.domain.dna import get_current_dna, get_trait_history
from profile_service.domain.profiles import get_profile_by_person
from profile_service.domain.snapshots import list_snapshots


async def _history_index(session: AsyncSession, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = await session.execute(
        text(
            "SELECT entity_type, entity_ref, occurred_at FROM history_index "
            "WHERE profile_id = :pid ORDER BY occurred_at"
        ),
        {"pid": profile_id},
    )
    return [dict(r) for r in rows.mappings()]


async def export_profile(session: AsyncSession, person_id: uuid.UUID) -> dict[str, Any] | None:
    """Assemble the full profile bundle for a person, or None if no profile."""
    profile = await get_profile_by_person(session, person_id)
    if profile is None:
        return None
    profile_id = profile["id"]
    return {
        "person_id": str(person_id),
        "profile": {
            "height_cm": profile["height_cm"],
            "stance": profile["stance"],
            "age_band": profile["age_band"],
            "dominant_hand": profile["dominant_hand"],
        },
        "dna_current": await get_current_dna(session, profile_id),
        "dna_history": await get_trait_history(session, profile_id),
        "snapshots": await list_snapshots(session, profile_id),
        "baselines": await list_baselines(session, profile_id),
        "history_index": await _history_index(session, profile_id),
    }


async def delete_profile(session: AsyncSession, person_id: uuid.UUID) -> bool:
    """Delete a person's profile (cascades to all child rows). True if removed."""
    result = await session.execute(
        text("DELETE FROM player_profiles WHERE person_id = :pid RETURNING id"),
        {"pid": person_id},
    )
    return result.first() is not None
