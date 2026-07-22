"""Plan + entitlement repository (M03 Step 2)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def list_active_plans(session: AsyncSession) -> list[dict[str, Any]]:
    """Return active plans (latest version per code) with their entitlements."""
    rows = await session.execute(
        text(
            "SELECT id, code, name, version, price_minor, currency "
            "FROM plans WHERE active = true ORDER BY price_minor"
        )
    )
    plans = [dict(r) for r in rows.mappings()]
    for plan in plans:
        plan["entitlements"] = await resolve_entitlements(session, plan["id"])
    return plans


async def get_plan_by_code(session: AsyncSession, code: str) -> dict[str, Any] | None:
    """Return the active plan with the given code (highest version)."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, code, name, version, price_minor, currency "
                    "FROM plans WHERE code = :c AND active = true "
                    "ORDER BY version DESC LIMIT 1"
                ),
                {"c": code},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def get_plan(session: AsyncSession, plan_id: uuid.UUID) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id, code, name, version, price_minor, currency "
                    "FROM plans WHERE id = :id"
                ),
                {"id": plan_id},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def resolve_entitlements(session: AsyncSession, plan_id: uuid.UUID) -> dict[str, str]:
    """Return the ``{key: value}`` entitlement map for a plan."""
    rows = await session.execute(
        text("SELECT key, value FROM plan_entitlements WHERE plan_id = :p"),
        {"p": plan_id},
    )
    return {r[0]: r[1] for r in rows}
