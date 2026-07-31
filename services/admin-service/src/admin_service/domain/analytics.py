"""Revenue + usage analytics over the warehouse (M20 Step 4, FR-M20-03/04).

Every number here is a real aggregate over :mod:`warehouse_repo`'s fact
tables — nothing here is estimated or modelled (Book 0 Trust Doctrine
applies to the admin console too). Two honesty limits worth stating
explicitly, since they shape what this module does NOT claim:

- ``revenue_minor_by_currency`` is realised revenue (summed ``invoice.paid``
  amounts) for the period, NOT a subscription-normalised MRR figure — this
  warehouse never captures a plan's periodic price, only what was actually
  charged, so a true MRR estimate is not something this data can honestly
  support yet.
- ``churn_rate`` is cancellations divided by subscriptions active at the
  START of the period (itself derived from cumulative ``created`` minus
  cumulative ``canceled`` events before that point) — returned as ``None``
  when that denominator is zero rather than reporting a meaningless rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SCHEMA = "warehouse"


@dataclass(frozen=True, slots=True)
class RevenueAnalytics:
    revenue_minor_by_currency: dict[str, int]
    invoice_count: int
    new_subscriptions: int
    cancellations: int
    upgrades: int
    downgrades: int
    churn_rate: float | None


@dataclass(frozen=True, slots=True)
class UsageAnalytics:
    analyses_started: int
    analyses_completed: int
    active_tenants: int
    active_players: int
    events_by_topic: dict[str, int] = field(default_factory=dict)


async def _count_subscription_actions_before(
    session: AsyncSession, *, action: str, before: datetime
) -> int:
    query = (
        f"SELECT count(*) FROM {SCHEMA}.fact_revenue_event "  # nosec B608 -- SCHEMA is a constant
        "WHERE event_topic = 'billing.subscription.changed' "
        "  AND payload->>'action' = :action AND occurred_at < :before"
    )
    result = await session.execute(text(query), {"action": action, "before": before})
    return int(result.scalar_one())


async def revenue_analytics(
    session: AsyncSession, *, period_start: datetime, period_end: datetime
) -> RevenueAnalytics:
    invoice_rows = (
        (
            await session.execute(
                text(
                    f"SELECT currency, sum(amount_minor) AS total, count(*) AS n "  # nosec B608
                    f"FROM {SCHEMA}.fact_revenue_event "
                    "WHERE event_topic = 'billing.invoice.paid' "
                    "  AND occurred_at >= :start AND occurred_at < :end "
                    "GROUP BY currency"
                ),
                {"start": period_start, "end": period_end},
            )
        )
        .mappings()
        .all()
    )
    revenue_by_currency = {
        r["currency"]: int(r["total"]) for r in invoice_rows if r["currency"] is not None
    }
    invoice_count = sum(int(r["n"]) for r in invoice_rows)

    async def _count_action(action: str) -> int:
        query = (
            f"SELECT count(*) FROM {SCHEMA}.fact_revenue_event "  # nosec B608
            "WHERE event_topic = 'billing.subscription.changed' "
            "  AND payload->>'action' = :action "
            "  AND occurred_at >= :start AND occurred_at < :end"
        )
        result = await session.execute(
            text(query), {"action": action, "start": period_start, "end": period_end}
        )
        return int(result.scalar_one())

    new_subscriptions = await _count_action("created")
    cancellations = await _count_action("canceled")
    upgrades = await _count_action("upgraded")
    downgrades = await _count_action("downgraded")

    created_before = await _count_subscription_actions_before(
        session, action="created", before=period_start
    )
    canceled_before = await _count_subscription_actions_before(
        session, action="canceled", before=period_start
    )
    active_at_start = created_before - canceled_before
    churn_rate = (cancellations / active_at_start) if active_at_start > 0 else None

    return RevenueAnalytics(
        revenue_minor_by_currency=revenue_by_currency,
        invoice_count=invoice_count,
        new_subscriptions=new_subscriptions,
        cancellations=cancellations,
        upgrades=upgrades,
        downgrades=downgrades,
        churn_rate=churn_rate,
    )


async def usage_analytics(
    session: AsyncSession, *, period_start: datetime, period_end: datetime
) -> UsageAnalytics:
    async def _distinct_correlations(topic: str) -> int:
        query = (
            "SELECT count(DISTINCT correlation_id) "
            f"FROM {SCHEMA}.fact_usage_event "  # nosec B608 -- SCHEMA is a constant
            "WHERE event_topic = :topic AND occurred_at >= :start AND occurred_at < :end"
        )
        result = await session.execute(
            text(query), {"topic": topic, "start": period_start, "end": period_end}
        )
        return int(result.scalar_one())

    analyses_started = await _distinct_correlations("video.normalized")
    analyses_completed = await _distinct_correlations("report.ready")

    active_tenants_row = await session.execute(
        text(
            "SELECT count(DISTINCT tenant_id) "
            f"FROM {SCHEMA}.fact_usage_event "  # nosec B608 -- SCHEMA is a constant
            "WHERE occurred_at >= :start AND occurred_at < :end"
        ),
        {"start": period_start, "end": period_end},
    )
    active_tenants = int(active_tenants_row.scalar_one())

    active_players_row = await session.execute(
        text(
            "SELECT count(DISTINCT payload->>'person_id') "
            f"FROM {SCHEMA}.fact_usage_event "  # nosec B608 -- SCHEMA is a constant
            "WHERE event_topic = 'video.normalized' AND payload ? 'person_id' "
            "  AND occurred_at >= :start AND occurred_at < :end"
        ),
        {"start": period_start, "end": period_end},
    )
    active_players = int(active_players_row.scalar_one())

    topic_rows = (
        (
            await session.execute(
                text(
                    "SELECT event_topic, count(*) AS n "
                    f"FROM {SCHEMA}.fact_usage_event "  # nosec B608 -- SCHEMA is a constant
                    "WHERE occurred_at >= :start AND occurred_at < :end "
                    "GROUP BY event_topic"
                ),
                {"start": period_start, "end": period_end},
            )
        )
        .mappings()
        .all()
    )
    events_by_topic = {r["event_topic"]: int(r["n"]) for r in topic_rows}

    return UsageAnalytics(
        analyses_started=analyses_started,
        analyses_completed=analyses_completed,
        active_tenants=active_tenants,
        active_players=active_players,
        events_by_topic=events_by_topic,
    )
