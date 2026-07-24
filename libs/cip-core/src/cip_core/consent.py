"""Shared consent + membership access check (used from M04 onward).

M04 profiles are anchored to the global *person*, not to a tenant, so they
can't use tenant row-level security to decide who may read a player's data.
Instead, access is authorised here against the M02 consent + membership
tables. This helper lives in cip-core — rather than in identity-service or
duplicated in each consumer — so every service enforces consent through **one
audited implementation** (the architecture decision for M04): no cross-service
HTTP on the read path (which would blow the <50ms attribute-read budget), and
a single source of truth.

Coupling note: this module issues SQL against M02-owned tables (``consents``,
``guardianships``, ``memberships``, ``persons``). That coupling is deliberate
and accepted — the alternative (an HTTP call to identity-service per read)
violates NFR-M04-01/05. The tables are read-only from here; identity-service
remains their sole writer. The caller passes an ``AsyncSession`` (same pattern
as :func:`cip_core.audit.record`) so cip-core stays independent of cip-data.

Decision order in :func:`check_profile_access` (first match wins):
1. self      — reader is the subject.
2. admin     — reader holds ``platform_admin`` (ops/support; audit it).
3. guardian  — reader has a verified guardianship over a minor subject.
4. sharing   — reader has a coaching role, shares an active tenant with the
               subject, AND the subject granted an active 'sharing' consent
               that covers that tenant (or is blanket).
5. deny.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import roles

#: Consent that the subject's data may be processed/analysed at all. The base
#: gate for the analysis pipeline (M10 attribute reads).
CONSENT_PROCESSING = "processing"
#: Consent that the subject's profile/DNA may be shared with coaches/staff.
CONSENT_SHARING = "sharing"
#: Consent that the subject's CLIPS may be retained and labelled as MODEL
#: TRAINING DATA. Deliberately distinct from :data:`CONSENT_PROCESSING`:
#: agreeing to have your own batting analysed is not agreeing to become
#: someone else's training corpus (Book 1 data strategy; M07 §12).
CONSENT_TRAINING = "training"

#: Roles that can read an assigned player's profile *if* sharing is consented.
_COACHING_ROLES = (roles.COACH, roles.ACADEMY_ADMIN, roles.ORG_ADMIN)


@dataclass(frozen=True, slots=True)
class AccessDecision:
    """Outcome of a profile-access check.

    ``reason`` is a stable slug for both the allow and deny paths — it goes
    into the audit ``meta`` so a denied read is explainable after the fact.
    """

    allowed: bool
    reason: str  # self | platform_admin | guardian | sharing_consent |
    #              no_consent | no_membership | not_permitted


async def has_active_consent(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    consent_type: str,
    tenant_id: uuid.UUID | None = None,
) -> bool:
    """True if ``person_id`` has a live (non-withdrawn) consent of this type.

    When ``tenant_id`` is given, matches consents scoped to that tenant OR
    blanket consents (``consents.tenant_id IS NULL``).
    """
    if tenant_id is None:
        result = await session.execute(
            text(
                "SELECT 1 FROM consents "
                "WHERE person_id = :pid AND type = :ct AND withdrawn_at IS NULL "
                "LIMIT 1"
            ),
            {"pid": person_id, "ct": consent_type},
        )
    else:
        result = await session.execute(
            text(
                "SELECT 1 FROM consents "
                "WHERE person_id = :pid AND type = :ct AND withdrawn_at IS NULL "
                "  AND (tenant_id IS NULL OR tenant_id = :tid) "
                "LIMIT 1"
            ),
            {"pid": person_id, "ct": consent_type, "tid": tenant_id},
        )
    return result.first() is not None


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
            "  AND verified = true LIMIT 1"
        ),
        {"m": minor_person_id, "g": guardian_person_id},
    )
    return result.first() is not None


async def shared_active_tenants(
    session: AsyncSession,
    *,
    person_a: uuid.UUID,
    person_b: uuid.UUID,
) -> set[uuid.UUID]:
    """Tenants where BOTH people are active members (coach/player overlap)."""
    result = await session.execute(
        text(
            "SELECT ma.tenant_id "
            "FROM memberships ma "
            "JOIN memberships mb ON ma.tenant_id = mb.tenant_id "
            "WHERE ma.person_id = :a AND mb.person_id = :b "
            "  AND ma.status = 'active' AND mb.status = 'active'"
        ),
        {"a": person_a, "b": person_b},
    )
    return {r[0] for r in result}


async def check_profile_access(
    session: AsyncSession,
    *,
    subject_person_id: uuid.UUID,
    reader_person_id: uuid.UUID,
    reader_roles: tuple[str, ...],
    purpose: str = "read",
) -> AccessDecision:
    """Decide whether ``reader`` may access ``subject``'s profile/DNA.

    ``purpose`` is carried for the audit trail (e.g. 'read', 'read_dna') and
    does not change the decision today — every profile read shares one policy.
    """
    _ = purpose  # reserved for finer-grained policy later; audited meanwhile

    # 1. Self-access.
    if reader_person_id == subject_person_id:
        return AccessDecision(allowed=True, reason="self")

    # 2. Platform admin (ops/support) — always allowed, always audited.
    if roles.PLATFORM_ADMIN in reader_roles:
        return AccessDecision(allowed=True, reason="platform_admin")

    # 3. Guardian of a minor subject.
    if await has_verified_guardianship(
        session, minor_person_id=subject_person_id, guardian_person_id=reader_person_id
    ):
        return AccessDecision(allowed=True, reason="guardian")

    # 4. Coach/staff with an active shared tenant + the subject's sharing consent.
    if any(r in _COACHING_ROLES for r in reader_roles):
        shared = await shared_active_tenants(
            session, person_a=reader_person_id, person_b=subject_person_id
        )
        if not shared:
            return AccessDecision(allowed=False, reason="no_membership")
        # Sharing consent scoped to one of the shared tenants (or blanket).
        for tenant_id in shared:
            if await has_active_consent(
                session,
                person_id=subject_person_id,
                consent_type=CONSENT_SHARING,
                tenant_id=tenant_id,
            ):
                return AccessDecision(allowed=True, reason="sharing_consent")
        return AccessDecision(allowed=False, reason="no_consent")

    return AccessDecision(allowed=False, reason="not_permitted")


@dataclass(frozen=True, slots=True)
class TrainingConsentDecision:
    """Outcome of a training-data consent check, with an auditable reason."""

    allowed: bool
    reason: str  # training_consent | guardian_consent | no_training_consent |
    #              minor_requires_guardian_consent | unknown_person


async def may_use_for_training(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    tenant_id: uuid.UUID | None = None,
) -> TrainingConsentDecision:
    """Decide whether this person's frames may enter the annotation corpus.

    Deny by default. An adult needs a live :data:`CONSENT_TRAINING`. A MINOR
    needs that consent to have been granted **by a verified guardian** — a
    child cannot sign their own data into a training set, so a self-granted
    consent on a minor's account is refused (Book 0 §11.1, M07 AC-M07-07).

    Withdrawal is honoured implicitly: ``withdrawn_at`` filtering means a
    person who revokes training consent stops qualifying immediately, and
    already-queued frames are removed by the caller's withdrawal handling.
    """
    person = (
        await session.execute(
            text("SELECT dob_band FROM persons WHERE id = :pid"),
            {"pid": person_id},
        )
    ).first()
    if person is None:
        return TrainingConsentDecision(allowed=False, reason="unknown_person")

    granted_by = [
        row[0]
        for row in (
            await session.execute(
                text(
                    "SELECT granted_by FROM consents "
                    "WHERE person_id = :pid AND type = :ct AND withdrawn_at IS NULL "
                    "  AND (tenant_id IS NULL OR tenant_id = :tid OR :tid IS NULL)"
                ),
                {"pid": person_id, "ct": CONSENT_TRAINING, "tid": tenant_id},
            )
        ).all()
    ]
    if not granted_by:
        return TrainingConsentDecision(allowed=False, reason="no_training_consent")

    if person[0] != "minor":
        return TrainingConsentDecision(allowed=True, reason="training_consent")

    for guardian_id in granted_by:
        if await has_verified_guardianship(
            session, minor_person_id=person_id, guardian_person_id=guardian_id
        ):
            return TrainingConsentDecision(allowed=True, reason="guardian_consent")
    return TrainingConsentDecision(allowed=False, reason="minor_requires_guardian_consent")
