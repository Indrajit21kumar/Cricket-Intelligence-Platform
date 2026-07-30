"""Health endpoints.

Book 3 §7 requires liveness + readiness probes and NFR-M01-02 pins both to
<100ms under normal load. Liveness is a trivial in-memory response. Readiness
pings every hard dependency in parallel with a short per-check timeout.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from reasoning_service import __version__
from reasoning_service.deps import Deps, get_deps

router = APIRouter(tags=["health"])

CHECK_TIMEOUT_SECONDS = 0.5


@router.get("/health/live")
def health_live() -> dict[str, str]:
    """Process is up. No I/O — always <10ms."""
    return {"status": "live"}


@router.get("/health/ready")
async def health_ready(
    response: Response,
    deps: Annotated[Deps, Depends(get_deps)],
) -> dict[str, Any]:
    """All hard dependencies are reachable (DB / Redis / Kafka in parallel)."""
    results = await asyncio.gather(
        _check_postgres(deps),
        _check_redis(deps),
        _check_kafka(deps),
        return_exceptions=True,
    )
    checks = {
        "postgres": _classify(results[0]),
        "redis": _classify(results[1]),
        "kafka": _classify(results[2]),
    }
    all_ok = all(v == "ok" for v in checks.values())
    response.status_code = 200 if all_ok else 503
    return {"status": "ready" if all_ok else "not_ready", "checks": checks}


async def _check_postgres(deps: Deps) -> None:
    async def _query() -> None:
        async with deps.engine.begin() as conn:
            await conn.execute(text("SELECT 1"))

    await asyncio.wait_for(_query(), timeout=CHECK_TIMEOUT_SECONDS)


async def _check_redis(deps: Deps) -> None:
    async def _ping() -> None:
        await deps.idempotency_store._client.ping()

    await asyncio.wait_for(_ping(), timeout=CHECK_TIMEOUT_SECONDS)


async def _check_kafka(deps: Deps) -> None:
    async def _probe() -> None:
        producer = deps.event_bus._producer
        if producer is None:
            raise RuntimeError("Kafka producer not started")
        result = await producer.partitions_for("cip.health.probe")
        if result is None:
            raise RuntimeError("Kafka metadata refresh failed")

    await asyncio.wait_for(_probe(), timeout=CHECK_TIMEOUT_SECONDS)


def _classify(result: BaseException | None) -> str:
    if result is None:
        return "ok"
    if isinstance(result, TimeoutError | asyncio.TimeoutError):
        return "timeout"
    return f"error: {type(result).__name__}"


version_router = APIRouter(tags=["internal"])


@version_router.get("/internal/version")
def internal_version() -> dict[str, str]:
    return {"service": "reasoning-service", "version": __version__}
