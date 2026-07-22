"""Canonical plan catalogue + idempotent seeding (M03 Step 2).

Book 0 §9 defines four commercial tiers. Prices here are placeholders in
minor currency units (paise) and are meant to be edited by platform_admin;
the entitlement *keys* are the stable contract feature modules depend on.

Seeding is idempotent (upsert by plan code+version), so it can run on every
deploy without duplicating rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from billing_service.domain.entitlements import (
    ANALYSIS_QUOTA_MONTHLY,
    FEATURE_AI_COACH,
    FEATURE_LEGEND_COMPARISON,
    FEATURE_PARTNER_API,
    SEATS_MAX,
    UNLIMITED,
)


@dataclass(frozen=True, slots=True)
class PlanDef:
    code: str
    name: str
    price_minor: int  # paise; 0 = free / custom-contract
    currency: str
    entitlements: dict[str, str] = field(default_factory=dict)


# Placeholder prices (INR paise). ₹499 Pro, ₹9,999 Academy. Free + Enterprise
# priced at 0 (Enterprise is contract-based).
CANONICAL_PLANS: tuple[PlanDef, ...] = (
    PlanDef(
        code="starter",
        name="Starter",
        price_minor=0,
        currency="INR",
        entitlements={
            ANALYSIS_QUOTA_MONTHLY: "5",
            FEATURE_AI_COACH: "false",
            FEATURE_LEGEND_COMPARISON: "false",
            FEATURE_PARTNER_API: "false",
            SEATS_MAX: "1",
        },
    ),
    PlanDef(
        code="pro",
        name="Pro",
        price_minor=49900,
        currency="INR",
        entitlements={
            ANALYSIS_QUOTA_MONTHLY: str(UNLIMITED),
            FEATURE_AI_COACH: "true",
            FEATURE_LEGEND_COMPARISON: "true",
            FEATURE_PARTNER_API: "false",
            SEATS_MAX: "1",
        },
    ),
    PlanDef(
        code="academy",
        name="Academy",
        price_minor=999900,
        currency="INR",
        entitlements={
            ANALYSIS_QUOTA_MONTHLY: str(UNLIMITED),
            FEATURE_AI_COACH: "true",
            FEATURE_LEGEND_COMPARISON: "true",
            FEATURE_PARTNER_API: "false",
            SEATS_MAX: "25",
        },
    ),
    PlanDef(
        code="enterprise",
        name="Enterprise",
        price_minor=0,
        currency="INR",
        entitlements={
            ANALYSIS_QUOTA_MONTHLY: str(UNLIMITED),
            FEATURE_AI_COACH: "true",
            FEATURE_LEGEND_COMPARISON: "true",
            FEATURE_PARTNER_API: "true",
            SEATS_MAX: "100",
        },
    ),
)


async def seed_catalogue(session: AsyncSession, *, version: int = 1) -> int:
    """Upsert the canonical plans + entitlements. Returns number of plans seeded.

    Idempotent: keyed on (code, version). Re-running updates name/price and
    the entitlement values without creating duplicates.
    """
    for plan in CANONICAL_PLANS:
        # Upsert the plan row.
        existing = (
            await session.execute(
                text("SELECT id FROM plans WHERE code = :c AND version = :v"),
                {"c": plan.code, "v": version},
            )
        ).first()
        if existing is not None:
            plan_id = uuid.UUID(str(existing[0]))
            await session.execute(
                text(
                    "UPDATE plans SET name = :n, price_minor = :p, currency = :cur, "
                    "active = true, updated_at = now() WHERE id = :id"
                ),
                {
                    "n": plan.name,
                    "p": plan.price_minor,
                    "cur": plan.currency,
                    "id": plan_id,
                },
            )
        else:
            plan_id = uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO plans (id, code, name, version, price_minor, currency) "
                    "VALUES (:id, :c, :n, :v, :p, :cur)"
                ),
                {
                    "id": plan_id,
                    "c": plan.code,
                    "n": plan.name,
                    "v": version,
                    "p": plan.price_minor,
                    "cur": plan.currency,
                },
            )

        # Upsert each entitlement (unique on plan_id + key).
        for key, value in plan.entitlements.items():
            await session.execute(
                text(
                    "INSERT INTO plan_entitlements (id, plan_id, key, value) "
                    "VALUES (:id, :pid, :k, :v) "
                    "ON CONFLICT (plan_id, key) DO UPDATE SET value = EXCLUDED.value, "
                    "updated_at = now()"
                ),
                {"id": uuid.uuid4(), "pid": plan_id, "k": key, "v": value},
            )

    return len(CANONICAL_PLANS)
