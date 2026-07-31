"""Model oversight (M20 Step 5, FR-M20-05).

Per-model health over ``warehouse.fact_model_metric``: accuracy-vs-golden
trend, drift (the change in accuracy across the window — not a separately
invented score), and confidence calibration. No production service
publishes this telemetry yet (see the Step 5 migration's docstring), so
this module's read side honestly reports "no data yet" (``None``/empty)
rather than fabricating a number — the same Trust Doctrine every analytical
module in this platform applies to its own outputs.

:data:`KNOWN_MODELS` is the golden-dataset-gated model set from M06-M09
(pose/bat/ball/shot) — the models Book 3's validation gates actually cover.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SCHEMA = "warehouse"

ACCURACY_VS_GOLDEN: Final[str] = "accuracy_vs_golden"
CONFIDENCE_MEAN: Final[str] = "confidence_mean"

#: The models this build's golden-dataset gates actually validate.
KNOWN_MODELS: Final[tuple[str, ...]] = ("pose", "bat", "ball", "shot")


@dataclass(frozen=True, slots=True)
class ModelHealth:
    model_name: str
    sample_count: int
    latest_accuracy: float | None
    latest_accuracy_at: datetime | None
    accuracy_trend: list[tuple[datetime, float]]
    #: Latest accuracy minus earliest accuracy in the window — signed, so a
    #: negative value means accuracy has fallen. None with fewer than 2 points.
    drift: float | None
    confidence_mean: float | None
    confidence_mean_at: datetime | None


async def record_model_metric(
    session: AsyncSession,
    *,
    model_name: str,
    model_version: str,
    metric_name: str,
    value: float,
    computed_at: datetime,
) -> uuid.UUID:
    metric_id = uuid.uuid4()
    await session.execute(
        text(
            f"INSERT INTO {SCHEMA}.fact_model_metric "  # nosec B608 -- SCHEMA is a constant
            "  (id, model_name, model_version, metric_name, value, computed_at) "
            "VALUES (:id, :name, :version, :metric, :value, :computed)"
        ),
        {
            "id": metric_id,
            "name": model_name,
            "version": model_version,
            "metric": metric_name,
            "value": value,
            "computed": computed_at,
        },
    )
    return metric_id


async def _series(
    session: AsyncSession, *, model_name: str, metric_name: str, since: datetime, until: datetime
) -> list[tuple[datetime, float]]:
    query = (
        "SELECT computed_at, value "
        f"FROM {SCHEMA}.fact_model_metric "  # nosec B608 -- SCHEMA is a constant
        "WHERE model_name = :name AND metric_name = :metric "
        "  AND computed_at >= :since AND computed_at <= :until "
        "ORDER BY computed_at"
    )
    rows = (
        await session.execute(
            text(query),
            {"name": model_name, "metric": metric_name, "since": since, "until": until},
        )
    ).all()
    return [(r[0], float(r[1])) for r in rows]


async def model_health(
    session: AsyncSession, *, model_name: str, since: datetime, until: datetime | None = None
) -> ModelHealth:
    window_end = until or datetime.now(UTC)
    accuracy_trend = await _series(
        session,
        model_name=model_name,
        metric_name=ACCURACY_VS_GOLDEN,
        since=since,
        until=window_end,
    )
    confidence_series = await _series(
        session, model_name=model_name, metric_name=CONFIDENCE_MEAN, since=since, until=window_end
    )

    latest_accuracy_at, latest_accuracy = (None, None)
    if accuracy_trend:
        latest_accuracy_at, latest_accuracy = accuracy_trend[-1]

    drift = None
    if len(accuracy_trend) >= 2:
        drift = accuracy_trend[-1][1] - accuracy_trend[0][1]

    confidence_mean_at, confidence_mean = (None, None)
    if confidence_series:
        confidence_mean_at, confidence_mean = confidence_series[-1]

    return ModelHealth(
        model_name=model_name,
        sample_count=len(accuracy_trend),
        latest_accuracy=latest_accuracy,
        latest_accuracy_at=latest_accuracy_at,
        accuracy_trend=accuracy_trend,
        drift=drift,
        confidence_mean=confidence_mean,
        confidence_mean_at=confidence_mean_at,
    )
