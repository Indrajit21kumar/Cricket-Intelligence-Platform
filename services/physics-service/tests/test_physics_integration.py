"""Physics compute + persist + publish (M11 Step 7).

Covers:
- AC-M11-01 inputs -> a PhysicsReport with PH-01..PH-11
- AC-M11-02 the compute runs from a fixture report + anthropometrics, no vision
- AC-M11-03 every estimate carries a confidence; provenance split intact
- AC-M11-05 ball-exit omitted (not fabricated) when no tracked ball
- FR-M11-08 physics.metrics is published with the full quantity set
- NFR-M11-03 re-delivery is idempotent
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from cip_core import roles
from cip_events import EventEnvelope, InMemoryIdempotencyStore, KafkaEventBus
from physics_service.domain.anthropometry import Anthropometrics
from physics_service.domain.biomech_input import from_report_payload
from physics_service.domain.quantities import ESTIMATED_IDS, PH_10, PH_IDS
from physics_service.domain.sources import PhysicsInputs
from physics_service.main import create_app
from physics_service.service import (
    TOPIC_BIOMECHANICS_METRICS,
    TOPIC_PHYSICS_METRICS,
    build_physics_consumer,
)

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"
DEFAULT_BOOTSTRAP = "localhost:9092"


@pytest_asyncio.fixture
async def app_client(
    _migrated_database: str,
) -> AsyncIterator[tuple[FastAPI, httpx.AsyncClient]]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield app, ac


def _token(*claim_roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _headers(tenant_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(roles.PLAYER)}", "X-Tenant-ID": str(tenant_id)}


def _corr() -> str:
    return f"m11-{uuid.uuid4().hex[:12]}"


def _body(correlation_id: str) -> dict[str, Any]:
    return {"correlation_id": correlation_id, "person_id": None}


def _seed(
    app: FastAPI, correlation_id: str, payload: dict[str, Any], *, height_cm: float | None = 180.0
) -> None:
    """Seed the fake source with inputs built purely from an M10 report payload.

    The bio is parsed from the report payload alone (no pose/video), which is the
    purity boundary in action (AC-M11-02).
    """
    bio = from_report_payload({**payload, "correlation_id": correlation_id})
    anthro = Anthropometrics(height_cm=height_cm, body_mass_kg=75.0) if height_cm else None
    app.state.deps.source.set_inputs(correlation_id, PhysicsInputs(bio=bio, anthropometrics=anthro))


class TestCompute:
    async def test_inputs_produce_all_eleven_quantities(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """AC-M11-01 + AC-M11-02: computed from a fixture report, no vision stack."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())

        r = await client.post(
            "/internal/v1/physics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        assert r.status_code == 200, r.text
        report = r.json()
        assert set(report["quantities"]) == set(PH_IDS)
        assert report["shot_type"] == "cover_drive"
        assert report["model_version"] == "phys-est-1.0.0"

    async def test_every_estimate_carries_a_confidence(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """AC-M11-03."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())
        r = await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        quantities = r.json()["quantities"]
        for eid in ESTIMATED_IDS:
            entry = quantities[eid]
            assert entry["provenance"] == "estimated"
            if entry["value"] is not None:
                assert entry["confidence"] is not None

    async def test_ball_exit_omitted_without_tracked_ball(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """AC-M11-05: absolute timing = no ball -> PH-10 omitted, not fabricated."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload(flags=["ABSOLUTE_TIMING"]))
        r = await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        ph10 = r.json()["quantities"][PH_10]
        assert ph10["value"] is None
        assert ph10["omitted_reason"] == "no_tracked_ball_contact"

    async def test_no_inputs_is_unprocessable(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 422


class TestProvisional:
    async def test_provisional_report_is_202(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload(provisional=True))
        r = await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 202
        assert r.json()["provisional"] is True


class TestIdempotency:
    async def test_recompute_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """NFR-M11-03."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())
        for _ in range(2):
            await client.post(
                "/internal/v1/physics/compute",
                headers=_headers(tenant_id),
                json=_body(correlation_id),
            )
        async with app.state.deps.engine.begin() as conn:
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM physics_reports WHERE correlation_id = :c"),
                    {"c": correlation_id},
                )
            ).scalar_one()
        assert count == 1


class TestReadRun:
    async def test_get_returns_the_report(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())
        await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/physics/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["correlation_id"] == correlation_id

    async def test_other_tenant_cannot_read(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())
        await client.post(
            "/internal/v1/physics/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/physics/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_physics_metrics_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """FR-M11-08: the report is published for M12/M13/M14/M15."""
        app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m11-phy-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_PHYSICS_METRICS, group_id=group)
            correlation_id = _corr()
            _seed(app, correlation_id, make_payload())
            r = await client.post(
                "/internal/v1/physics/compute",
                headers=_headers(tenant_id),
                json=_body(correlation_id),
            )
            assert r.status_code == 200, r.text

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if env.payload.get("correlation_id") == correlation_id:
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.tenant_id == tenant_id
            assert set(env.payload["quantities"]) == set(PH_IDS)
            assert "kinetic_chain" in env.payload
        finally:
            await bus.stop()


class TestConsumer:
    async def test_biomechanics_metrics_drives_a_report(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID, make_payload: Any
    ) -> None:
        """The production trigger: biomechanics.metrics in, a persisted report out."""
        app, client = app_client
        consumer = build_physics_consumer(
            app.state.deps, idempotency_store=InMemoryIdempotencyStore()
        )
        correlation_id = _corr()
        _seed(app, correlation_id, make_payload())
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.1.0",
            idempotency_key=f"{TOPIC_BIOMECHANICS_METRICS}:{correlation_id}",
            payload={"person_id": None, "shot_type": "cover_drive"},
        )
        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True and first.success is True
        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False  # deduped

        r = await client.get(f"/v1/physics/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
