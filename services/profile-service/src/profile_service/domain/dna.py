"""Cricket DNA store — current traits + append-only history (M04 Step 3).

The Cricket DNA is a versioned set of technical trait scores. M04 STORES it;
M16 (the Cricket DNA engine) COMPUTES it and is the ONLY writer (ENG-004
boundary, AC-M04-03). Every write does two things atomically:

1. UPSERTs the ``dna_traits`` row (the current value per trait), and
2. APPENDS a ``dna_trait_history`` row.

History is append-only (NFR-M04-02): we never UPDATE or DELETE a history row,
so the full trajectory of any trait is reconstructable to any prior point
(:func:`reconstruct_dna_at`).

Trust Doctrine (Book 0 §8): every trait value carries a ``provenance``
(measured | estimated | modelled) + optional ``confidence`` (0..1). M16
supplies both on the write path (FR-M04-04).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

PROVENANCE_MEASURED = "measured"
PROVENANCE_ESTIMATED = "estimated"
PROVENANCE_MODELLED = "modelled"
PROVENANCE_VALUES = frozenset({PROVENANCE_MEASURED, PROVENANCE_ESTIMATED, PROVENANCE_MODELLED})


@dataclass(frozen=True, slots=True)
class TraitUpdate:
    """One trait update from M16."""

    trait_key: str
    value: str
    provenance: str
    confidence: float | None = None
    source_ref: str | None = None


async def write_traits(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID,
    updates: list[TraitUpdate],
    now: datetime | None = None,
) -> int:
    """Apply a batch of trait updates: UPSERT current + append history.

    All updates in one call share a single ``snapshot_at`` so a reconstruction
    at that instant sees the whole batch consistently. Returns the count.
    """
    snapshot_at = now or datetime.now(UTC)
    for u in updates:
        await session.execute(
            text(
                "INSERT INTO dna_traits "
                "  (id, profile_id, trait_key, value, confidence, provenance, source_ref) "
                "VALUES (:id, :pid, :key, :val, :conf, :prov, :src) "
                "ON CONFLICT (profile_id, trait_key) DO UPDATE SET "
                "  value = EXCLUDED.value, confidence = EXCLUDED.confidence, "
                "  provenance = EXCLUDED.provenance, source_ref = EXCLUDED.source_ref, "
                "  updated_at = now()"
            ),
            {
                "id": uuid.uuid4(),
                "pid": profile_id,
                "key": u.trait_key,
                "val": u.value,
                "conf": u.confidence,
                "prov": u.provenance,
                "src": u.source_ref,
            },
        )
        await session.execute(
            text(
                "INSERT INTO dna_trait_history "
                "  (id, profile_id, trait_key, value, confidence, provenance, "
                "   source_ref, snapshot_at) "
                "VALUES (:id, :pid, :key, :val, :conf, :prov, :src, :at)"
            ),
            {
                "id": uuid.uuid4(),
                "pid": profile_id,
                "key": u.trait_key,
                "val": u.value,
                "conf": u.confidence,
                "prov": u.provenance,
                "src": u.source_ref,
                "at": snapshot_at,
            },
        )
    return len(updates)


async def get_current_dna(session: AsyncSession, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """All current trait values for a profile (the live Cricket DNA)."""
    rows = await session.execute(
        text(
            "SELECT trait_key, value, confidence, provenance, source_ref, updated_at "
            "FROM dna_traits WHERE profile_id = :pid ORDER BY trait_key"
        ),
        {"pid": profile_id},
    )
    return [dict(r) for r in rows.mappings()]


async def get_trait_history(
    session: AsyncSession,
    profile_id: uuid.UUID,
    *,
    trait_key: str | None = None,
) -> list[dict[str, Any]]:
    """Append-only history for a profile, optionally filtered to one trait."""
    if trait_key is None:
        rows = await session.execute(
            text(
                "SELECT trait_key, value, confidence, provenance, source_ref, snapshot_at "
                "FROM dna_trait_history WHERE profile_id = :pid "
                "ORDER BY snapshot_at, trait_key"
            ),
            {"pid": profile_id},
        )
    else:
        rows = await session.execute(
            text(
                "SELECT trait_key, value, confidence, provenance, source_ref, snapshot_at "
                "FROM dna_trait_history WHERE profile_id = :pid AND trait_key = :key "
                "ORDER BY snapshot_at"
            ),
            {"pid": profile_id, "key": trait_key},
        )
    return [dict(r) for r in rows.mappings()]


async def reconstruct_dna_at(
    session: AsyncSession, profile_id: uuid.UUID, at: datetime
) -> list[dict[str, Any]]:
    """Reconstruct each trait's value as of ``at`` (NFR-M04-02).

    For every trait, the latest history row with ``snapshot_at <= at``.
    """
    rows = await session.execute(
        text(
            "SELECT DISTINCT ON (trait_key) "
            "  trait_key, value, confidence, provenance, snapshot_at "
            "FROM dna_trait_history "
            "WHERE profile_id = :pid AND snapshot_at <= :at "
            "ORDER BY trait_key, snapshot_at DESC"
        ),
        {"pid": profile_id, "at": at},
    )
    return [dict(r) for r in rows.mappings()]
