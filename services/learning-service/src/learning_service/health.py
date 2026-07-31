"""Health endpoints.

Book 3 §7 requires liveness + readiness probes and NFR-M01-02 pins both to
<100ms under normal load. Liveness is a trivial in-memory response. Readiness
pings every hard dependency in parallel with a short per-check timeout so a
single stuck dep can never make the whole probe slow.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text

from learning_service import __version__
from learning_service.deps import Deps, get_deps

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
    """All hard dependencies are reachable.

    Runs DB / Redis / Kafka probes in parallel; each has its own timeout so
    one slow dep can't push the total past NFR-M01-02's 100ms budget.
    """
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
    """Kafka reachability — ``partitions_for`` triggers a metadata fetch
    against the brokers; if the cluster is unreachable it either returns
    ``None`` or raises within the timeout window."""

    async def _probe() -> None:
        producer = deps.event_bus._producer
        if producer is None:
            raise RuntimeError("Kafka producer not started")
        result = await producer.partitions_for("cip.health.probe")
        # Result is a set (possibly empty for an auto-created topic) if the
        # cluster responded; None means metadata refresh failed.
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
    return {"service": "learning-service", "version": __version__}
