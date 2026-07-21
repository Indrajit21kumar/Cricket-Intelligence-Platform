"""Consent + guardianship repository (M02 Step 6).

The activation gate for minors (Book 0 §11.1, FR-M02-06): a person whose
``dob_band = 'minor'`` sits in ``pending_consent`` after email verification
and CANNOT log in until BOTH exist:

1. a *verified* guardianship linking them to a guardian, and
2. an active (non-withdrawn) ``processing`` consent granted by that guardian.

When both hold, :func:`activate_minor_if_eligible` flips the minor to
``active``. Withdrawing the consent flips them back to ``pending_consent``.

For M02 the guardianship is auto-verified on creation (self-declared, per
the age-verification decision). Real guardian identity verification — an
email round-trip to the guardian, or an ID check — is a later compliance
ticket handled with M19 (Notification) + a KYC vendor.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The consent type that gates minor activation.
PROCESSING = "processing"


async def create_guardianship(
    session: AsyncSession,
    *,
    minor_person_id: uuid.UUID,
    guardian_person_id: uuid.UUID,
    verified: bool = True,
) -> uuid.UUID:
    """Link a minor to a guardian. Returns the guardianship id.

    Idempotent on (minor, guardian): re-creating the same link returns the
    existing id rather than raising, so a guardian can safely retry.
    """
    existing = await session.execute(
        text("SELECT id FROM guardianships WHERE minor_person_id = :m AND guardian_person_id = :g"),
        {"m": minor_person_id, "g": guardian_person_id},
    )
    row = existing.first()
    if row is not None:
        return uuid.UUID(str(row[0]))

    gid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO guardianships "
            "  (id, minor_person_id, guardian_person_id, verified) "
            "VALUES (:id, :m, :g, :v)"
        ),
        {"id": gid, "m": minor_person_id, "g": guardian_person_id, "v": verified},
    )
    return gid


async def has_verified_guardianship(
    session: AsyncSession,
    *,
    minor_person_id: uuid.UUID,
    guardian_person_id: uuid.UUID,
) -> bool:
    """True if a verified guardianship links this guardian to this minor."""
    result = await session.execute(
        text(
            "SELECT 1 FROM guardianships "
            "WHERE minor_person_id = :m AND guardian_person_id = :g "
            "  AND verified = true"
        ),
        {"m": minor_person_id, "g": guardian_person_id},
    )
    return result.first() is not None


async def create_consent(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    granted_by: uuid.UUID,
    consent_type: str,
    scope: dict[str, Any] | None = None,
    tenant_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Record a consent. Returns the consent id."""
    cid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO consents "
            "  (id, person_id, tenant_id, type, granted_by, scope) "
            "VALUES (:id, :pid, :tid, :type, :by, cast(:scope as jsonb))"
        ),
        {
            "id": cid,
            "pid": person_id,
            "tid": tenant_id,
            "type": consent_type,
            "by": granted_by,
            "scope": json.dumps(scope or {}),
        },
    )
    return cid


async def withdraw_consent(
    session: AsyncSession, *, consent_id: uuid.UUID, by_person_id: uuid.UUID
) -> dict[str, Any] | None:
    """Mark a consent withdrawn. Returns the affected row, or None.

    Only the person who granted the consent may withdraw it (enforced via
    the ``granted_by`` predicate).
    """
    result = await session.execute(
        text(
            "UPDATE consents SET withdrawn_at = now() "
            "WHERE id = :id AND granted_by = :by AND withdrawn_at IS NULL "
            "RETURNING id, person_id, type"
        ),
        {"id": consent_id, "by": by_person_id},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def has_active_guardian_consent(session: AsyncSession, *, minor_person_id: uuid.UUID) -> bool:
    """True if the minor has a live processing-consent from a verified guardian."""
    result = await session.execute(
        text(
            "SELECT 1 FROM consents c "
            "JOIN guardianships g "
            "  ON g.minor_person_id = c.person_id "
            "  AND g.guardian_person_id = c.granted_by "
            "  AND g.verified = true "
            "WHERE c.person_id = :m "
            "  AND c.type = :ptype "
            "  AND c.withdrawn_at IS NULL"
        ),
        {"m": minor_person_id, "ptype": PROCESSING},
    )
    return result.first() is not None


async def get_person_dob_and_status(
    session: AsyncSession, *, person_id: uuid.UUID
) -> tuple[str | None, str] | None:
    """Return ``(dob_band, status)`` for a person, or None if absent."""
    result = await session.execute(
        text("SELECT dob_band, status FROM persons WHERE id = :id"),
        {"id": person_id},
    )
    row = result.first()
    return (row[0], row[1]) if row else None


async def activate_minor_if_eligible(session: AsyncSession, *, minor_person_id: uuid.UUID) -> str:
    """Flip a pending_consent minor to active iff consent conditions hold.

    Returns the resulting status. No-op (returns current status) for adults
    or minors who aren't currently pending_consent.
    """
    info = await get_person_dob_and_status(session, person_id=minor_person_id)
    if info is None:
        return "unknown"
    dob_band, status = info
    if dob_band != "minor" or status != "pending_consent":
        return status
    if await has_active_guardian_consent(session, minor_person_id=minor_person_id):
        await session.execute(
            text("UPDATE persons SET status = 'active', updated_at = now() WHERE id = :id"),
            {"id": minor_person_id},
        )
        return "active"
    return status


async def restrict_minor_if_consent_lost(
    session: AsyncSession, *, minor_person_id: uuid.UUID
) -> str:
    """Flip an active minor back to pending_consent if consent no longer holds.

    Called after a withdrawal. Returns the resulting status.
    """
    info = await get_person_dob_and_status(session, person_id=minor_person_id)
    if info is None:
        return "unknown"
    dob_band, status = info
    if dob_band != "minor" or status != "active":
        return status
    if not await has_active_guardian_consent(session, minor_person_id=minor_person_id):
        await session.execute(
            text(
                "UPDATE persons SET status = 'pending_consent', updated_at = now() WHERE id = :id"
            ),
            {"id": minor_person_id},
        )
        return "pending_consent"
    return status


async def list_consents_for_person(
    session: AsyncSession, *, person_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Return consents recorded FOR a person (as the subject)."""
    result = await session.execute(
        text(
            "SELECT id, type, granted_by, granted_at, withdrawn_at "
            "FROM consents WHERE person_id = :pid ORDER BY granted_at"
        ),
        {"pid": person_id},
    )
    return [dict(r) for r in result.mappings()]
