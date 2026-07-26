"""Shared fixtures for physics-service tests.

Integration tests spin up the full app under the real lifespan — Postgres +
Redis + Kafka must be running (docker-compose up locally, service containers
+ Redpanda step in CI).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head
from physics_service.domain.biomech_input import BiomechanicsInput, MetricInput
from physics_service.main import create_app

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
# M11 reads M02-owned tables (persons, consents, guardianships) through the
# cip-core consent layer for consent-scoped report access, so the identity
# schema must exist for the integration tests.
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"
PHY_MIGRATIONS = REPO_ROOT / "services" / "physics-service" / "migrations"


# A plausible, complete BiomechanicsReport: (value, provenance, confidence) per
# BM metric. BM-15 (weight transfer) is M10's one estimated proxy; every other
# metric is measured. A realistic side-on cover drive.
_DEFAULT_METRICS: dict[str, tuple[float, str, float]] = {
    "BM-01": (5.0, "measured", 0.90),  # head stability (cm)
    "BM-02": (90.0, "measured", 0.90),  # shoulder rotation (deg)
    "BM-03": (60.0, "measured", 0.88),  # hip rotation (deg)
    "BM-04": (45.0, "measured", 0.87),  # X-factor / separation (deg)
    "BM-05": (12.0, "measured", 0.80),  # pelvic tilt (deg)
    "BM-06": (150.0, "measured", 0.85),  # front knee flexion (deg)
    "BM-07": (20.0, "measured", 0.75),  # foot alignment (deg)
    "BM-08": (55.0, "measured", 0.75),  # stride length (%height)
    "BM-09": (140.0, "measured", 0.82),  # backlift (deg)
    "BM-10": (0.85, "measured", 0.80),  # bat path linearity (ratio)
    "BM-11": (30.0, "measured", 0.83),  # bat lag (deg)
    "BM-12": (20.0, "measured", 0.80),  # hand speed (m/s)
    "BM-13": (120.0, "measured", 0.80),  # follow-through (deg)
    "BM-14": (300.0, "measured", 0.70),  # balance recovery (ms)
    "BM-15": (0.60, "estimated", 0.50),  # weight transfer (ratio) — M10 proxy
    "BM-16": (12.0, "measured", 0.80),  # centre-of-mass path (cm)
    "BM-17": (40.0, "measured", 0.75),  # ground-contact timing (ms)
}

_DEFAULT_PHASES: dict[str, int] = {
    "stance": 0,
    "backlift": 4,
    "downswing": 8,
    "impact": 14,
    "follow_through": 20,
}

BioFactory = Callable[..., BiomechanicsInput]
PayloadFactory = Callable[..., dict[str, Any]]


def _build_metrics(
    *,
    drop: tuple[str, ...] = (),
    disabled: Mapping[str, str] | None = None,
    overrides: Mapping[str, MetricInput] | None = None,
) -> dict[str, MetricInput]:
    metrics: dict[str, MetricInput] = {}
    for mid, (value, prov, conf) in _DEFAULT_METRICS.items():
        if mid in drop:
            continue
        metrics[mid] = MetricInput(value=value, provenance=prov, confidence=conf)
    for mid, reason in (disabled or {}).items():
        metrics[mid] = MetricInput(
            value=None, provenance="measured", confidence=0.0, disabled_reason=reason
        )
    for mid, mi in (overrides or {}).items():
        metrics[mid] = mi
    return metrics


@pytest.fixture
def make_bio() -> BioFactory:
    """Factory for a typed :class:`BiomechanicsInput` (an M10 report M11 reads)."""

    def _make(
        *,
        correlation_id: str = "stroke-1",
        person_id: str | None = "11111111-1111-1111-1111-111111111111",
        shot_type: str | None = "cover_drive",
        shot_confidence: float | None = 0.8,
        phases: Mapping[str, int] | None = None,
        phase_method: str = "standard",
        fps: float = 60.0,
        spatial_confidence: str = "high",
        depth_estimated: bool = True,
        mean_pose_confidence: float = 0.9,
        provisional: bool = False,
        flags: tuple[str, ...] = (),
        out_of_expected_range: bool = False,
        schema_version: str = "biomechanics.metrics/1.1",
        drop: tuple[str, ...] = (),
        disabled: Mapping[str, str] | None = None,
        overrides: Mapping[str, MetricInput] | None = None,
    ) -> BiomechanicsInput:
        return BiomechanicsInput(
            correlation_id=correlation_id,
            person_id=person_id,
            shot_type=shot_type,
            shot_confidence=shot_confidence,
            phase_boundaries=dict(phases) if phases is not None else dict(_DEFAULT_PHASES),
            phase_method=phase_method,
            metrics=_build_metrics(drop=drop, disabled=disabled, overrides=overrides),
            fps=fps,
            spatial_confidence=spatial_confidence,
            depth_estimated=depth_estimated,
            mean_pose_confidence=mean_pose_confidence,
            provisional=provisional,
            flags=flags,
            out_of_expected_range=out_of_expected_range,
            schema_version=schema_version,
        )

    return _make


@pytest.fixture
def make_payload() -> PayloadFactory:
    """Factory for the raw ``biomechanics.metrics`` payload M10 publishes."""

    def _make(
        *,
        correlation_id: str = "stroke-1",
        person_id: str | None = "11111111-1111-1111-1111-111111111111",
        fps: float = 60.0,
        spatial_confidence: str = "high",
        depth_estimated: bool = True,
        provisional: bool = False,
        flags: list[str] | None = None,
        out_of_expected_range: bool = False,
    ) -> dict[str, Any]:
        metrics = {
            mid: {"value": v, "provenance": prov, "confidence": conf}
            for mid, (v, prov, conf) in _DEFAULT_METRICS.items()
        }
        return {
            "correlation_id": correlation_id,
            "person_id": person_id,
            "shot_type": "cover_drive",
            "shot_confidence": 0.8,
            "phase_boundaries": dict(_DEFAULT_PHASES),
            "phase_method": "standard",
            "metrics": metrics,
            "quality": {
                "mean_pose_confidence": 0.9,
                "spatial_confidence": spatial_confidence,
                "depth_estimated": depth_estimated,
                "phase_segmentation_method": "standard",
                "provisional": provisional,
                "fps": fps,
                "flags": flags or [],
                "out_of_expected_range_metrics": [],
            },
            "out_of_expected_range": out_of_expected_range,
            "provisional": provisional,
            "schema_version": "biomechanics.metrics/1.1",
        }

    return _make


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic JWT signing key so hand-crafted access tokens verify."""
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="session")
def _migrated_database() -> str:
    """Apply base + identity + physics migrations once (idempotent).

    Sync fixture — must NOT be async, because ``upgrade_head`` uses
    ``asyncio.run`` internally and would collide with the pytest-asyncio
    event loop if called from an async fixture.
    """
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
    upgrade_head(url, migrations_dir=PHY_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def integration_app(
    _migrated_database: str,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx AsyncClient bound to the fully-wired app.

    The lifespan runs, so DB engine + event bus + Redis are actually started
    and stopped around the test. Uses env-provided URLs (from the CI
    integration job or the local docker-compose).
    """
    app = create_app()
    # raise_app_exceptions=False lets the app's exception handler produce a
    # 500 envelope we can inspect (matches real HTTP behaviour). Without it,
    # httpx re-raises unhandled exceptions to the test as if the app crashed.
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        yield client


@pytest_asyncio.fixture
async def tenant_id(_migrated_database: str) -> uuid.UUID:
    """Create a fresh tenant in Postgres and return its id.

    Kept per-test (not session-scoped) so each test has its own isolation
    space + a stable tenant to bind requests to.
    """
    engine = build_engine(_migrated_database)
    session_factory = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(session_factory) as session:
            await session.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) "
                    "VALUES (:id, :name, 'academy', 'IN')"
                ),
                {"id": tid, "name": f"phy-svc-{uuid.uuid4().hex[:8]}"},
            )
        yield tid
    finally:
        await engine.dispose()
