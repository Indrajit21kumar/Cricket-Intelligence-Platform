"""Personal baseline computation (M04 Step 5, FR-M04-06, AC-M04-05).

A *personal baseline* (CIP-STD Book 4 Ch. 9, benchmark type "Personal") is a
player's own historical distribution for a CIP-STD metric — the reference M15
uses to measure improvement against the player themselves (SR-001).

M04 maintains one baseline per (profile, CIP-STD metric id, e.g. "BM-01"). The
analysis pipeline records a metric observation each time a value is measured;
M04 appends it and recomputes the summary distribution. The distribution is
served to M15 in the CIP-STD metric shape:

    {"metric_key": "BM-01",
     "distribution": {"count", "mean", "stddev", "min", "max",
                      "p25", "p50", "p75"}}

Raw samples are kept alongside the summary (inside the ``distribution`` JSONB
per the M04 §9 schema — no separate observations table) so percentiles can be
recomputed exactly as new values arrive. Personal-baseline sample counts are
small (a player's analyses over time), so this is cheap.
"""

from __future__ import annotations

import json
import re
import statistics
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: CIP-STD metric ids: a 2+ letter domain prefix + '-' + code (BM-01, PH-11,
#: SC-01, BN-04, KG-RISK-002). Appendix A, Book 4.
_METRIC_ID_RE = re.compile(r"^[A-Z]{2,3}-[A-Z0-9-]+$")


def is_valid_metric_id(metric_key: str) -> bool:
    return bool(_METRIC_ID_RE.match(metric_key))


def compute_summary(samples: list[float]) -> dict[str, Any]:
    """Summarise a sample set into the CIP-STD distribution shape.

    Pure function (typical / boundary / degenerate unit-tested). Uses the
    stdlib ``statistics`` module — sample stddev for n>=2 (0 for a single
    point), inclusive quartiles for the percentiles.
    """
    n = len(samples)
    if n == 0:
        return {
            "count": 0,
            "mean": None,
            "stddev": None,
            "min": None,
            "max": None,
            "p25": None,
            "p50": None,
            "p75": None,
        }
    ordered = sorted(samples)
    if n >= 2:
        p25, p50, p75 = statistics.quantiles(samples, n=4, method="inclusive")
        stddev = statistics.stdev(samples)
    else:
        p25 = p50 = p75 = ordered[0]
        stddev = 0.0
    return {
        "count": n,
        "mean": statistics.fmean(samples),
        "stddev": stddev,
        "min": ordered[0],
        "max": ordered[-1],
        "p25": p25,
        "p50": p50,
        "p75": p75,
    }


async def _load_samples(
    session: AsyncSession, profile_id: uuid.UUID, metric_key: str
) -> list[float]:
    row = (
        await session.execute(
            text(
                "SELECT distribution FROM personal_baselines "
                "WHERE profile_id = :pid AND metric_key = :m"
            ),
            {"pid": profile_id, "m": metric_key},
        )
    ).first()
    if row is None:
        return []
    dist = row[0] or {}
    samples = dist.get("samples", [])
    return [float(x) for x in samples]


async def record_observation(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID,
    metric_key: str,
    value: float,
) -> dict[str, Any]:
    """Append a metric observation and recompute the baseline distribution.

    Returns the updated summary (without the raw samples).
    """
    samples = await _load_samples(session, profile_id, metric_key)
    samples.append(float(value))
    summary = compute_summary(samples)
    distribution = {"summary": summary, "samples": samples}
    await session.execute(
        text(
            "INSERT INTO personal_baselines (id, profile_id, metric_key, distribution) "
            "VALUES (:id, :pid, :m, cast(:d as jsonb)) "
            "ON CONFLICT (profile_id, metric_key) DO UPDATE SET "
            "  distribution = EXCLUDED.distribution, updated_at = now()"
        ),
        {
            "id": uuid.uuid4(),
            "pid": profile_id,
            "m": metric_key,
            "d": json.dumps(distribution),
        },
    )
    return summary


async def get_baseline(
    session: AsyncSession, profile_id: uuid.UUID, metric_key: str
) -> dict[str, Any] | None:
    """Return one metric's baseline distribution (summary only), or None."""
    row = (
        (
            await session.execute(
                text(
                    "SELECT metric_key, distribution, updated_at FROM personal_baselines "
                    "WHERE profile_id = :pid AND metric_key = :m"
                ),
                {"pid": profile_id, "m": metric_key},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    dist = row["distribution"] or {}
    return {
        "metric_key": row["metric_key"],
        "distribution": dist.get("summary", {}),
        "updated_at": row["updated_at"],
    }


async def list_baselines(session: AsyncSession, profile_id: uuid.UUID) -> list[dict[str, Any]]:
    """All of a profile's baselines (summary only), in the CIP-STD shape."""
    rows = await session.execute(
        text(
            "SELECT metric_key, distribution, updated_at FROM personal_baselines "
            "WHERE profile_id = :pid ORDER BY metric_key"
        ),
        {"pid": profile_id},
    )
    out: list[dict[str, Any]] = []
    for r in rows.mappings():
        dist = r["distribution"] or {}
        out.append(
            {
                "metric_key": r["metric_key"],
                "distribution": dist.get("summary", {}),
                "updated_at": r["updated_at"],
            }
        )
    return out
