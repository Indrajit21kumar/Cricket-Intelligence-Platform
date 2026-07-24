"""Ball compute + persist + publish (M08 Step 7).

Covers:
- AC-M08-01 release/bounce/contact with per-event confidence
- AC-M08-03 speed emitted as ESTIMATED, never measured
- AC-M08-04 no reliable release -> timing_reference=absolute
- AC-M08-05 poor clips -> low confidence, NO fabricated events
- AC-M08-06 ball.events published with correct schema; re-delivery idempotent
- FR-M08-09 consented deliveries reach the shared annotation queue as 'ball'
"""

from __future__ import annotations

import asyncio
import json
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

from ball_service.domain.artefact import artefact_key
from ball_service.main import create_app
from ball_service.service import (
    TOPIC_BALL_EVENTS,
    TOPIC_VIDEO_NORMALIZED,
    build_ball_consumer,
)
from cip_annotation import MODALITY_BALL, MODALITY_BAT
from cip_core import CONSENT_TRAINING, roles
from cip_data.engine import admin_session, build_engine, build_session_factory
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
    return f"m08-{uuid.uuid4().hex[:12]}"


def _body(correlation_id: str, person_id: uuid.UUID | None = None, **overrides: object) -> dict:
    body: dict = {
        "correlation_id": correlation_id,
        "normalized_ref": f"tenant/x/normalized/{correlation_id}.mp4",
        "person_id": str(person_id) if person_id else None,
        "fps": 60.0,
        "camera_angle": "side_on",
        "pixel_to_meter": 0.004,
        "spatial_confidence": "high",
        "quality_flags": [],
    }
    body.update(overrides)
    return body


async def _seed_consented_person(database_url: str) -> uuid.UUID:
    engine = build_engine(database_url)
    try:
        sf = build_session_factory(engine)
        pid = uuid.uuid4()
        async with admin_session(sf) as s:
            await s.execute(
                text("INSERT INTO persons (id, email, dob_band) VALUES (:id, :e, 'adult')"),
                {"id": pid, "e": f"{pid}@example.test"},
            )
            await s.execute(
                text(
                    "INSERT INTO consents (id, person_id, type, granted_by, scope) "
                    "VALUES (:id, :pid, :ct, :pid, cast('{}' as jsonb))"
                ),
                {"id": uuid.uuid4(), "pid": pid, "ct": CONSENT_TRAINING},
            )
        return pid
    finally:
        await engine.dispose()


async def _queue_rows(database_url: str, correlation_id: str) -> list[tuple[str, str]]:
    engine = build_engine(database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text(
                    "SELECT modality, reason FROM annotation_queue "
                    "WHERE correlation_id = :c ORDER BY frame_index"
                ),
                {"c": correlation_id},
            )
            return [(r[0], r[1]) for r in result]
    finally:
        await engine.dispose()


class TestCompute:
    async def test_a_good_clip_produces_events(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-01: release + bounce with per-event confidence."""
        app, client = app_client
        correlation_id = _corr()

        r = await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["model_version"] == "fake-ball-v1"
        assert run["conditions_met"] is True
        assert run["frames_detected"] > 0

        events = run["events"]
        assert "release" in events and events["release"]["confidence"] > 0
        assert "bounce" in events and events["bounce"]["confidence"] > 0

        raw = await app.state.deps.artefact_store.load(
            artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        )
        assert raw is not None
        track = json.loads(raw)
        assert track["schema"] == "ball.track/1.0"
        assert len(track["positions"]) > 0

    async def test_speed_is_estimated_never_measured(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-03."""
        _app, client = app_client
        r = await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        speed = r.json()["events"].get("speed")
        assert speed is not None
        assert speed["provenance"] == "estimated"
        assert "monocular_depth" in speed["limited_by"]
        assert speed["metres_per_second"] > 0

    async def test_no_calibration_means_no_speed_but_still_events(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post(
            "/internal/ball/compute",
            headers=_headers(tenant_id),
            json=_body(_corr(), pixel_to_meter=None),
        )
        assert r.status_code == 200, r.text
        events = r.json()["events"]
        assert "speed" not in events
        assert "bounce" in events

    async def test_recompute_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-06: same correlation_id -> one row, one artefact."""
        app, client = app_client
        correlation_id = _corr()
        body = _body(correlation_id)

        first = await client.post("/internal/ball/compute", headers=_headers(tenant_id), json=body)
        second = await client.post("/internal/ball/compute", headers=_headers(tenant_id), json=body)
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["artefact_ref"] == second.json()["artefact_ref"]
        keys = [k for k in app.state.deps.artefact_store.objects if correlation_id in k]
        assert len(keys) == 1


class TestFailSafe:
    async def test_a_low_fps_clip_fabricates_nothing(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-05: deliberately poor clip -> low confidence, no events."""
        _app, client = app_client
        r = await client.post(
            "/internal/ball/compute",
            headers=_headers(tenant_id),
            json=_body(_corr(), fps=20.0),
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["conditions_met"] is False
        assert run["quality"] == "rejected"
        assert run["track_confidence"] <= 0.25
        assert run["artefact_ref"] is None
        # No fabricated events of any kind.
        events = run["events"]
        assert "release" not in events
        assert "bounce" not in events
        assert "contact" not in events
        assert "speed" not in events
        # AC-M08-04: and timing falls back.
        assert run["timing_reference"] == "absolute"

    async def test_no_ball_in_shot_reports_nothing_but_good_conditions(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """Distinguishable from a bad clip — that difference drives the UI copy."""
        app, client = app_client
        app.state.deps.tracker.patch(no_ball=True)

        r = await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["conditions_met"] is True  # the clip was fine
        assert run["frames_detected"] == 0  # there was just no ball
        assert run["quality"] == "rejected"
        assert run["events"] == {"timing_reference": "absolute"}


class TestTimingReference:
    async def test_a_good_clip_earns_release_relative(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        assert r.json()["timing_reference"] == "release_relative"

    async def test_losing_the_early_flight_falls_back_to_absolute(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-04: no reliable release -> M10 uses absolute timing."""
        app, client = app_client
        # Blank the first half: the ball is first seen mid-pitch.
        app.state.deps.tracker.patch(fail_frames=frozenset(range(0, 15)))

        r = await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["timing_reference"] == "absolute"
        assert "release" not in run["events"]


class TestAnnotationRouting:
    async def test_consented_delivery_is_queued_as_ball(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        """FR-M08-09, sharing M07's queue under a different modality."""
        _app, client = app_client
        person_id = await _seed_consented_person(_migrated_database)
        correlation_id = _corr()

        r = await client.post(
            "/internal/ball/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )
        assert r.status_code == 200, r.text
        rows = await _queue_rows(_migrated_database, correlation_id)
        assert rows, "expected queued frames"
        assert {modality for modality, _ in rows} == {MODALITY_BALL}
        assert MODALITY_BAT not in {modality for modality, _ in rows}

    async def test_unconsented_delivery_is_refused(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        r = await client.post(
            "/internal/ball/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, uuid.uuid4()),
        )
        assert r.status_code == 200, r.text
        assert await _queue_rows(_migrated_database, correlation_id) == []

    async def test_a_failed_delivery_still_feeds_the_corpus(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        """Hard cases are what a ball detector is short of."""
        app, client = app_client
        app.state.deps.tracker.patch(no_ball=True)
        person_id = await _seed_consented_person(_migrated_database)
        correlation_id = _corr()

        r = await client.post(
            "/internal/ball/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )
        assert r.status_code == 200, r.text
        rows = await _queue_rows(_migrated_database, correlation_id)
        assert rows
        assert {reason for _, reason in rows} == {"failed"}


class TestReadRun:
    async def test_get_returns_the_run_summary(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/ball/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["correlation_id"] == correlation_id

    async def test_unknown_correlation_is_404(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        assert (
            await client.get(f"/v1/ball/{_corr()}", headers=_headers(tenant_id))
        ).status_code == 404

    async def test_other_tenant_cannot_read_the_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        await client.post(
            "/internal/ball/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/ball/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_ball_events_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M08-06: schema + correlation_id, with M10's decision fields."""
        _app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m08-be-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_BALL_EVENTS, group_id=group)
            correlation_id = _corr()

            r = await client.post(
                "/internal/ball/compute", headers=_headers(tenant_id), json=_body(correlation_id)
            )
            assert r.status_code == 200, r.text

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if env.payload.get("correlation_id") == correlation_id:
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.tenant_id == tenant_id
            assert env.payload["model_version"] == "fake-ball-v1"
            assert env.payload["artefact_ref"] == r.json()["artefact_ref"]
            # The two fields M10 branches on.
            assert env.payload["events"]["timing_reference"] == "release_relative"
            assert env.payload["track_confidence"] > 0
            assert env.payload["conditions_met"] is True
            assert env.payload["fps"] == 60.0
        finally:
            await bus.stop()


class TestConsumer:
    async def test_video_normalized_drives_a_ball_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The production trigger: an event in, a persisted run out."""
        app, client = app_client
        consumer = build_ball_consumer(app.state.deps, idempotency_store=InMemoryIdempotencyStore())
        correlation_id = _corr()
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.1.0",
            idempotency_key=f"{TOPIC_VIDEO_NORMALIZED}:{correlation_id}",
            payload=_body(correlation_id),
        )

        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True and first.success is True

        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False  # deduped

        r = await client.get(f"/v1/ball/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        # fps travelled through the event, so the run is not condition-gated.
        assert r.json()["conditions_met"] is True
