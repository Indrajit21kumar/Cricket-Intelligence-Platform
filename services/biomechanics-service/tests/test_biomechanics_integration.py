"""Biomechanics compute + persist + publish (M10 Step 7).

Covers:
- AC-M10-01 full inputs -> a BiomechanicsReport with BM-01..BM-17
- AC-M10-03 low-confidence input -> provisional (202)
- AC-M10-04 out-of-range flagged, report still emitted
- AC-M10-07 the report carries everything M11 needs (no pose re-derivation)
- AC-M10-08 identical input -> identical output (determinism)
- NFR-M10-04 re-delivery is idempotent
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import text

from biomechanics_service.domain.builder import (
    RawBatFrame,
    RawPoseFrame,
    RawStroke,
)
from biomechanics_service.domain.catalogue import BM_IDS
from biomechanics_service.domain.stroke import (
    ANGLE_SIDE_ON,
    Anthropometrics,
    BallContext,
    Calibration,
    Phases,
)
from biomechanics_service.main import create_app
from biomechanics_service.service import (
    TOPIC_BIOMECHANICS_METRICS,
    TOPIC_SHOT_CLASSIFIED,
    build_biomechanics_consumer,
)
from cip_core import roles
from cip_events import EventEnvelope, InMemoryIdempotencyStore, KafkaEventBus

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
    return f"m10-{uuid.uuid4().hex[:12]}"


def _raw_stroke(
    *, confidence: float = 0.9, blade_x: float = 0.6, head_drift: float = 0.0
) -> RawStroke:
    """A plausible front-foot drive: pose + bat over 17 frames, side-on.

    ``head_drift`` moves the nose down-pitch across the stroke (image-x -> Z on
    side-on), driving BM-01 head stability — used to exercise the out-of-range
    path without touching anything else.
    """
    phases = Phases(
        stance=0, backlift=4, downswing=8, impact=12, follow_through=16, method="standard"
    )
    pose = []
    for i in range(17):
        pose.append(
            RawPoseFrame(
                frame_index=i,
                joints={
                    "nose": (head_drift * (i / 16), 1.7, confidence),
                    "left_shoulder": (0.2 + 0.005 * i, 1.4, confidence),
                    "right_shoulder": (-0.2, 1.4, confidence),
                    "left_hip": (0.15, 0.9, confidence),
                    "right_hip": (-0.15, 0.9, confidence),
                    "left_knee": (0.3, 0.5, confidence),
                    "left_ankle": (0.3, max(0.1, 0.4 - 0.05 * i), confidence),
                    "right_knee": (-0.1, 0.5, confidence),
                    "right_ankle": (-0.1, 0.1, confidence),
                    "left_wrist": (0.05 * i, 1.0, confidence),
                    "right_wrist": (0.05 * i, 1.0, confidence),
                    "left_elbow": (0.0, 1.2, confidence),
                },
            )
        )
        # Note: image_x maps to Z on side-on, so "z-translation" is encoded in x.
    bat = tuple(
        RawBatFrame(
            frame_index=i,
            detected=True,
            parts={
                "handle_bottom": (0.0, 0.8),
                "blade_tip": (blade_x, 0.5),
                "sweet_spot": (blade_x * 0.7, 0.6),
            },
        )
        for i in range(17)
    )
    return RawStroke(
        correlation_id="placeholder",
        pose=tuple(pose),
        bat=bat,
        phases=phases,
        ball=BallContext(release_frame=2, contact_frame=12, timing_reference="release_relative"),
        anthropometrics=Anthropometrics(height_cm=180.0, handedness="RHB"),
        calibration=Calibration(
            metres_per_unit=1.0,
            fps=60.0,
            camera_angle=ANGLE_SIDE_ON,
            spatial_confidence="high",
            depth_estimated=True,
        ),
        shot_type="cover_drive",
        shot_confidence=0.8,
    )


def _seed(app: FastAPI, correlation_id: str, raw: RawStroke) -> None:
    stroke = RawStroke(
        correlation_id=correlation_id,
        pose=raw.pose,
        bat=raw.bat,
        phases=raw.phases,
        ball=raw.ball,
        anthropometrics=raw.anthropometrics,
        calibration=raw.calibration,
        shot_type=raw.shot_type,
        shot_confidence=raw.shot_confidence,
        bat_downswing_failure_ratio=raw.bat_downswing_failure_ratio,
    )
    app.state.deps.stroke_source.set_stroke(correlation_id, stroke)


def _body(correlation_id: str) -> dict:
    return {"correlation_id": correlation_id, "person_id": None}


class TestCompute:
    async def test_full_inputs_produce_all_17_metrics(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M10-01."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())

        r = await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        assert r.status_code == 200, r.text
        report = r.json()
        assert set(report["metrics"]) == set(BM_IDS)
        assert report["shot_type"] == "cover_drive"
        assert report["phase_method"] == "standard"
        # Every metric carries provenance + confidence.
        for mv in report["metrics"].values():
            assert "provenance" in mv and "confidence" in mv

    async def test_report_is_self_contained_for_physics(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M10-07: M11 reads the report, never pose — so it must be complete."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())
        r = await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        report = r.json()
        # All 17 metrics + phases + quality present in the one payload.
        assert len(report["metrics"]) == 17
        assert "phase_boundaries" in report and "quality" in report

    async def test_no_inputs_is_unprocessable(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(_corr()),
        )
        assert r.status_code == 422


class TestDeterminism:
    async def test_identical_input_identical_output(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M10-08 + NFR-M10-03: same stroke twice -> same metrics."""
        app, client = app_client
        c1, c2 = _corr(), _corr()
        _seed(app, c1, _raw_stroke())
        _seed(app, c2, _raw_stroke())
        r1 = await client.post(
            "/internal/v1/biomechanics/compute", headers=_headers(tenant_id), json=_body(c1)
        )
        r2 = await client.post(
            "/internal/v1/biomechanics/compute", headers=_headers(tenant_id), json=_body(c2)
        )
        assert r1.json()["metrics"] == r2.json()["metrics"]

    async def test_recompute_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """NFR-M10-04."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())
        await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        async with app.state.deps.engine.begin() as conn:
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM biomechanics_reports WHERE correlation_id = :c"),
                    {"c": correlation_id},
                )
            ).scalar_one()
        assert count == 1


class TestProvisional:
    async def test_low_confidence_input_is_provisional_202(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M10-03: precondition failure -> provisional, 202."""
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke(confidence=0.3))
        r = await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        assert r.status_code == 202
        assert r.json()["provisional"] is True
        assert "LOW_CONFIDENCE_INPUT" in r.json()["quality"]["flags"]


class TestOutOfRange:
    async def test_out_of_range_is_flagged_not_rejected(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M10-04: an absurd bat geometry flags but the report still lands."""
        app, client = app_client
        correlation_id = _corr()
        # Head drifts 0.5m down the pitch -> BM-01 = 50cm, beyond the (0, 30) band.
        _seed(app, correlation_id, _raw_stroke(head_drift=0.5))
        r = await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        assert r.status_code in (200, 202), r.text
        assert r.json()["out_of_expected_range"] is True
        # The report was still stored and its review flag is queryable.
        async with app.state.deps.engine.begin() as conn:
            reviewed = (
                await conn.execute(
                    text(
                        "SELECT reviewed_by_human FROM biomechanics_reports "
                        "WHERE correlation_id = :c"
                    ),
                    {"c": correlation_id},
                )
            ).scalar_one()
        assert reviewed is False  # sits in the review queue


class TestReadRun:
    async def test_get_returns_the_report(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())
        await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        r = await client.get(f"/v1/biomechanics/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["correlation_id"] == correlation_id

    async def test_other_tenant_cannot_read(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())
        await client.post(
            "/internal/v1/biomechanics/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id),
        )
        r = await client.get(f"/v1/biomechanics/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_biomechanics_metrics_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """FR-M10-09: the report is published for M11 with the full metric set."""
        app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m10-bm-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_BIOMECHANICS_METRICS, group_id=group)
            correlation_id = _corr()
            _seed(app, correlation_id, _raw_stroke())
            r = await client.post(
                "/internal/v1/biomechanics/compute",
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
            assert set(env.payload["metrics"]) == set(BM_IDS)
            assert env.payload["shot_type"] == "cover_drive"
            assert "quality" in env.payload
        finally:
            await bus.stop()


class TestConsumer:
    async def test_shot_classified_drives_a_report(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The production trigger: shot.classified in, a persisted report out."""
        app, client = app_client
        consumer = build_biomechanics_consumer(
            app.state.deps, idempotency_store=InMemoryIdempotencyStore()
        )
        correlation_id = _corr()
        _seed(app, correlation_id, _raw_stroke())
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.0.0",
            idempotency_key=f"{TOPIC_SHOT_CLASSIFIED}:{correlation_id}",
            payload={"person_id": None, "shot_class": "cover_drive"},
        )
        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True and first.success is True
        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False  # deduped

        r = await client.get(f"/v1/biomechanics/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
