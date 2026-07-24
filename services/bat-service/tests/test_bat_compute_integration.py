"""Bat compute + persist + publish (M07 Step 7).

Covers:
- AC-M07-01 per-frame bat keypoints + bat_angle in the CIP frame
- AC-M07-03 poor downswing detection -> provisional, honoured by M10
- AC-M07-04 sweet spot and swing plane labelled derived in the artefact
- AC-M07-05 bat.tracked published with summary + quality; re-delivery idempotent
- AC-M07-07 only consented frames reach the annotation queue
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

from bat_service.domain.artefact import artefact_key
from bat_service.domain.bat import PROVENANCE_DERIVED, SWEET_SPOT
from bat_service.main import create_app
from bat_service.service import (
    TOPIC_BAT_TRACKED,
    TOPIC_VIDEO_NORMALIZED,
    build_bat_consumer,
)
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
    return f"m07-{uuid.uuid4().hex[:12]}"


def _body(correlation_id: str, person_id: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "correlation_id": correlation_id,
        "normalized_ref": f"tenant/x/normalized/{correlation_id}.mp4",
        "person_id": str(person_id) if person_id else None,
        "camera_angle": "side_on",
        "spatial_confidence": "high",
        "quality_flags": [],
    }


async def _seed_consented_person(database_url: str) -> uuid.UUID:
    """An adult who has consented to training use."""
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


async def _queue_count(database_url: str, correlation_id: str) -> int:
    engine = build_engine(database_url)
    try:
        sf = build_session_factory(engine)
        async with admin_session(sf) as s:
            # RLS hides rows from admin_session, so count with the owner role
            # via a direct connection instead.
            _ = s
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT count(*) FROM annotation_queue WHERE correlation_id = :c"),
                {"c": correlation_id},
            )
            return int(result.scalar_one())
    finally:
        await engine.dispose()


class TestCompute:
    async def test_clean_clip_produces_a_bat_track(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M07-01: bat parts + bat_angle per frame, in the CIP frame."""
        app, client = app_client
        correlation_id = _corr()

        r = await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["model_version"] == "fake-bat-v1"
        assert run["frame_count"] == 30
        assert run["frames_detected"] > 0
        assert run["quality"] in {"ok", "provisional"}

        key = artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        assert run["artefact_ref"] == key
        raw = await app.state.deps.artefact_store.load(key)
        assert raw is not None
        track = json.loads(raw)
        assert track["schema"] == "bat.track/1.0"
        assert len(track["frames"]) == 30

        detected = [f for f in track["frames"] if f["detected"]]
        assert detected, "expected at least one detected frame"
        for frame in detected:
            assert "bat_angle" in frame
            assert frame["bat_angle"]["provenance"] == PROVENANCE_DERIVED
            # AC-M07-04: the sweet spot is present and marked derived.
            sweet = [p for p in frame["parts"] if p["part"] == SWEET_SPOT]
            assert sweet and sweet[0]["provenance"] == PROVENANCE_DERIVED

    async def test_pose_puts_the_track_in_the_true_cip_frame(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """With M06 available, the bat shares the body's stance origin."""
        app, client = app_client
        correlation_id = _corr()
        # A real M06 artefact: wrists near the fake bat's handle, 1080p frame.
        app.state.deps.pose_client.set_payload(
            correlation_id,
            json.dumps(
                {
                    "schema": "pose.keypoints/1.1",
                    "frame": {
                        "origin_x": 960.0,
                        "origin_y": 594.0,
                        "scale": 1080.0,
                        "y_up": True,
                    },
                    "frames": [
                        [
                            {"joint": "left_wrist", "x": -0.01, "y": 0.0, "confidence": 0.9},
                            {"joint": "right_wrist", "x": 0.01, "y": 0.0, "confidence": 0.9},
                        ]
                        for _ in range(30)
                    ],
                }
            ),
        )

        r = await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        assert r.json()["frames_detected"] == 30

        raw = await app.state.deps.artefact_store.load(
            artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        )
        assert raw is not None
        track = json.loads(raw)
        handle = next(p for p in track["frames"][0]["parts"] if p["part"] == "handle_bottom")
        # The fake bat's handle sits at the fake batter's hands, i.e. the origin.
        assert handle["x"] == pytest.approx(0.0, abs=0.02)
        assert handle["y"] == pytest.approx(0.0, abs=0.02)

    async def test_untrained_detector_reports_no_dataset_version(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """A detector with no corpus behind it says so rather than implying one."""
        _app, client = app_client
        r = await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200
        assert r.json()["dataset_version"] is None

    async def test_poor_downswing_detection_is_provisional(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M07-03: the flag M10 honours."""
        app, client = app_client
        # Blank the whole second half of the clip: the bat is lost through the
        # downswing and never comes back.
        app.state.deps.detector.patch(fail_frames=frozenset(range(15, 30)))

        r = await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        assert r.json()["provisional"] is True
        assert r.json()["quality"] == "provisional"

    async def test_total_detection_failure_is_rejected(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        app.state.deps.detector.patch(fail_frames=frozenset(range(30)))

        r = await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 200, r.text
        assert r.json()["quality"] == "rejected"
        assert r.json()["artefact_ref"] is None  # nothing worth storing
        assert r.json()["mean_confidence"] is None

    async def test_recompute_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M07-05: same correlation_id -> one row, one artefact."""
        app, client = app_client
        correlation_id = _corr()
        body = _body(correlation_id)

        first = await client.post("/internal/bat/compute", headers=_headers(tenant_id), json=body)
        second = await client.post("/internal/bat/compute", headers=_headers(tenant_id), json=body)
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["artefact_ref"] == second.json()["artefact_ref"]
        keys = [k for k in app.state.deps.artefact_store.objects if correlation_id in k]
        assert len(keys) == 1


class TestAnnotationRouting:
    async def test_consented_player_frames_reach_the_queue(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        """FR-M07-08: the flywheel turns for players who opted in."""
        _app, client = app_client
        person_id = await _seed_consented_person(_migrated_database)
        correlation_id = _corr()

        r = await client.post(
            "/internal/bat/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )
        assert r.status_code == 200, r.text
        assert await _queue_count(_migrated_database, correlation_id) > 0

    async def test_unconsented_player_frames_are_refused(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        """AC-M07-07: no training consent, no corpus — the run still succeeds."""
        _app, client = app_client
        correlation_id = _corr()

        r = await client.post(
            "/internal/bat/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, uuid.uuid4()),  # person who never consented
        )
        assert r.status_code == 200, r.text
        assert await _queue_count(_migrated_database, correlation_id) == 0


class TestReadRun:
    async def test_get_returns_the_run_summary(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/bat/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["correlation_id"] == correlation_id

    async def test_unknown_correlation_is_404(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.get(f"/v1/bat/{_corr()}", headers=_headers(tenant_id))
        assert r.status_code == 404

    async def test_other_tenant_cannot_read_the_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        await client.post(
            "/internal/bat/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/bat/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_bat_tracked_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M07-05: artefact ref + summary + quality, with M05 context."""
        _app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m07-bt-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_BAT_TRACKED, group_id=group)
            correlation_id = _corr()

            r = await client.post(
                "/internal/bat/compute", headers=_headers(tenant_id), json=_body(correlation_id)
            )
            assert r.status_code == 200, r.text

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if env.payload.get("correlation_id") == correlation_id:
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.tenant_id == tenant_id
            assert env.payload["artefact_ref"] == r.json()["artefact_ref"]
            assert env.payload["model_version"] == "fake-bat-v1"
            assert env.payload["quality"] in {"ok", "provisional"}
            assert env.payload["provisional"] is r.json()["provisional"]
            assert env.payload["camera_angle"] == "side_on"
            assert env.payload["spatial_confidence"] == "high"
            # Downstream can tell how well the bat was attributed.
            assert "hand_associated_frames" in env.payload
            # No M06 pose in this test, so the track is honestly labelled as
            # clip-relative rather than sharing the body's stance origin.
            assert env.payload["frame_basis"] == "clip_relative"
        finally:
            await bus.stop()


class TestConsumer:
    async def test_video_normalized_drives_a_bat_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The production trigger: an event in, a persisted run out."""
        app, client = app_client
        consumer = build_bat_consumer(app.state.deps, idempotency_store=InMemoryIdempotencyStore())
        correlation_id = _corr()
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.0.0",
            idempotency_key=f"{TOPIC_VIDEO_NORMALIZED}:{correlation_id}",
            payload=_body(correlation_id),
        )

        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True and first.success is True

        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False  # deduped

        r = await client.get(f"/v1/bat/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        keys = [k for k in app.state.deps.artefact_store.objects if correlation_id in k]
        assert len(keys) == 1
