"""benchmark_profiles repository (M15 Step 7, §9).

Platform-GLOBAL, no RLS — Book 5 (CIBL) reference data, read via
``admin_session`` like M12's knowledge tables. Only ``released`` rows are
ever selected for comparison (NFR-M15-05, AC-M15-06); authoring/seeding
released profiles is a Book 5 governance process outside this build's v1
API (this module is read-only, mirroring how M15's own spec only lists a
``GET /v1/benchmarks/profiles`` listing endpoint, no create/author route).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from benchmark_service.domain.profiles import BenchmarkProfile

_COLUMNS = "benchmark_id, type, scope, distributions, version, released"


def _to_profile(row: dict[str, Any]) -> BenchmarkProfile:
    return BenchmarkProfile(
        benchmark_id=row["benchmark_id"],
        type=row["type"],
        scope=row["scope"],
        distributions=row["distributions"],
        version=row["version"],
        released=row["released"],
    )


async def list_released_profiles(session: AsyncSession) -> list[BenchmarkProfile]:
    """Every RELEASED profile — the only ones comparison may ever use."""
    query = f"SELECT {_COLUMNS} FROM benchmark_profiles WHERE released"  # nosec B608 -- constant columns
    rows = (await session.execute(text(query))).mappings().all()
    return [_to_profile(dict(row)) for row in rows]
