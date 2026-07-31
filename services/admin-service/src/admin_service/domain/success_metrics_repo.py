"""Success-metric board (M20 Step 7, §13 KPIs: accuracy, retention, academies, countries).

``inference_time`` is deliberately NOT included: no service in this
platform publishes per-run latency telemetry anywhere the warehouse can
read it, and Book 0's Trust Doctrine means this board doesn't get to report
a number that isn't real — the same honesty limit Step 4/5 documented for
MRR and "no data yet" model health.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_service.domain import model_metrics_repo

SCHEMA = "warehouse"


@dataclass(frozen=True, slots=True)
class SuccessMetrics:
    total_academies: int
    countries: int
    average_model_accuracy: float | None
    models_with_accuracy_data: int
    active_tenants_previous_period: int
    retained_tenants: int
    #: retained / active_previous_period. None when the previous period had
    #: no active tenants (a rate with a zero denominator isn't honest either).
    retention_rate: float | None


async def _academy_and_country_counts(session: AsyncSession) -> tuple[int, int]:
    row = (
        await session.execute(
            text(
                "SELECT count(*) FILTER (WHERE type = 'academy') AS academies, "
                "       count(DISTINCT region) FILTER (WHERE region IS NOT NULL) AS countries "
                "FROM tenants"
            )
        )
    ).one()
    return int(row.academies), int(row.countries)


async def _average_model_accuracy(
    session: AsyncSession, *, since: datetime
) -> tuple[float | None, int]:
    accuracies = []
    for name in model_metrics_repo.KNOWN_MODELS:
        health = await model_metrics_repo.model_health(session, model_name=name, since=since)
        if health.latest_accuracy is not None:
            accuracies.append(health.latest_accuracy)
    if not accuracies:
        return None, 0
    return sum(accuracies) / len(accuracies), len(accuracies)


async def _tenant_retention(
    session: AsyncSession,
    *,
    previous_period_start: datetime,
    period_start: datetime,
    period_end: datetime,
) -> tuple[int, int]:
    row = (
        await session.execute(
            text(
                f"WITH prev AS ("  # nosec B608 -- SCHEMA is a constant, rest is bound params
                f"  SELECT DISTINCT tenant_id FROM {SCHEMA}.fact_usage_event "
                "   WHERE occurred_at >= :prev_start AND occurred_at < :period_start"
                "), curr AS ("
                f"  SELECT DISTINCT tenant_id FROM {SCHEMA}.fact_usage_event "
                "   WHERE occurred_at >= :period_start AND occurred_at < :period_end"
                ") "
                "SELECT (SELECT count(*) FROM prev) AS active_previous, "
                "       (SELECT count(*) FROM prev JOIN curr USING (tenant_id)) AS retained"
            ),
            {
                "prev_start": previous_period_start,
                "period_start": period_start,
                "period_end": period_end,
            },
        )
    ).one()
    return int(row.active_previous), int(row.retained)


async def compute_success_metrics(
    session: AsyncSession,
    *,
    previous_period_start: datetime,
    period_start: datetime,
    period_end: datetime,
) -> SuccessMetrics:
    academies, countries = await _academy_and_country_counts(session)
    avg_accuracy, models_with_data = await _average_model_accuracy(session, since=period_start)
    active_previous, retained = await _tenant_retention(
        session,
        previous_period_start=previous_period_start,
        period_start=period_start,
        period_end=period_end,
    )
    retention_rate = (retained / active_previous) if active_previous > 0 else None
    return SuccessMetrics(
        total_academies=academies,
        countries=countries,
        average_model_accuracy=avg_accuracy,
        models_with_accuracy_data=models_with_data,
        active_tenants_previous_period=active_previous,
        retained_tenants=retained,
        retention_rate=retention_rate,
    )
