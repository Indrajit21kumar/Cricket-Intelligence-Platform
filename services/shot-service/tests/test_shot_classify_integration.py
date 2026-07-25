"""Shot classify + persist + publish (M09 Step 5).

Covers:
- AC-M09-01 classified into the taxonomy with a confidence
- AC-M09-05 degrades to pose-only when bat/ball are unavailable
- AC-M09-06 shot.classified published with correct schema; re-delivery idempotent
- FR-M09-08 abstentions/low-confidence reach the shared queue as 'shot'
"""

from __future__ import annotations

import asyncio
import json
import math
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

from cip_annotation import MODALITY_SHOT
from cip_core import CONSENT_TRAINING, roles
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_events import EventEnvelope, InMemoryIdempotencyStore, KafkaEventBus
from shot_service.main import create_app
from shot_service.service import (
    TOPIC_POSE_KEYPOINTS,
    TOPIC_SHOT_CLASSIFIED,
    build_shot_consumer,
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
    return f"m09-{uuid.uuid4().hex[:12]}"


def _pose_artefact(frames: int = 24) -> str:
    """A front-foot driving stroke: hands rise then sweep across and down."""
    top = frames // 3
    frame_list = []
    for i in range(frames):
        y = 0.6 + 0.5 * (i / top) if i <= top else 1.1 - 0.6 * ((i - top) / (frames - 1 - top))
        hand_x = -0.1 + 0.4 * (i / (frames - 1))
        frame_list.append(
            [
                {"joint": "left_wrist", "x": hand_x - 0.02, "y": y, "confidence": 0.9},
                {"joint": "right_wrist", "x": hand_x + 0.02, "y": y, "confidence": 0.9},
                {"joint": "left_shoulder", "x": -0.1, "y": 1.3, "confidence": 0.9},
                {
                    "joint": "right_shoulder",
                    "x": 0.1 + 0.15 * (i / frames),
                    "y": 1.3,
                    "confidence": 0.9,
                },
                {"joint": "left_hip", "x": 0.1 * (i / frames), "y": 0.9, "confidence": 0.9},
                {"joint": "right_hip", "x": 0.1 * (i / frames), "y": 0.9, "confidence": 0.9},
                {"joint": "left_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
                {"joint": "right_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
            ]
        )
    return json.dumps(
        {
            "schema": "pose.keypoints/1.1",
            "frame": {"origin_x": 960.0, "origin_y": 600.0, "scale": 1080.0, "y_up": True},
            "frames": frame_list,
        }
    )


def _bat_event(inclination: float = 18.0) -> dict:
    return {
        "swing_plane": {
            "inclination_degrees": inclination,
            "confidence": 0.7,
            "provenance": "derived",
        },
        "frames_detected": 20,
        "provisional": False,
    }


def _ball_event(*, contact_frame: int = 16, timing: str = "release_relative") -> dict:
    return {
        "events": {
            "timing_reference": timing,
            "contact": {"frame_index": contact_frame, "confidence": 0.7},
            "line": {"value": "outside_off", "confidence": 0.6},
        },
        "conditions_met": True,
    }


def _seed_full(app: FastAPI, correlation_id: str, *, bat: bool = True, ball: bool = True) -> None:
    app.state.deps.pose_source.set_payload(correlation_id, _pose_artefact())
    if bat:
        app.state.deps.bat_source.set_event(correlation_id, _bat_event())
    if ball:
        app.state.deps.ball_source.set_event(correlation_id, _ball_event())


def _body(correlation_id: str, person_id: uuid.UUID | None = None) -> dict:
    return {
        "correlation_id": correlation_id,
        "person_id": str(person_id) if person_id else None,
        "camera_angle": "side_on",
    }


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


class TestClassify:
    async def test_full_fusion_classifies_the_stroke(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M09-01 + AC-M09-04 (standard method from a usable ball contact)."""
        app, client = app_client
        correlation_id = _corr()
        _seed_full(app, correlation_id)

        r = await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["model_version"] == "fake-shot-v1"
        assert run["shot_confidence"] > 0
        assert set(run["signals_used"]) == {"pose", "bat", "ball"}
        assert run["phase_method"] == "standard"
        assert set(run["phase_boundaries"]) == {
            "stance",
            "backlift",
            "downswing",
            "impact",
            "follow_through",
        }
        # Ball-anchored impact.
        assert run["phase_boundaries"]["impact"] == 16

    async def test_pose_only_still_classifies_with_fallback_phases(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M09-05: degrades to pose-only."""
        app, client = app_client
        correlation_id = _corr()
        _seed_full(app, correlation_id, bat=False, ball=False)

        r = await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["signals_used"] == ["pose"]
        assert run["phase_method"] == "bat_only_fallback"

    async def test_no_pose_is_unprocessable(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """A clip M06 rejected has no pose, so there is nothing to classify."""
        _app, client = app_client
        r = await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=_body(_corr())
        )
        assert r.status_code == 422

    async def test_reclassify_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M09-06."""
        app, client = app_client
        correlation_id = _corr()
        _seed_full(app, correlation_id)
        body = _body(correlation_id)

        first = await client.post("/internal/shot/classify", headers=_headers(tenant_id), json=body)
        second = await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=body
        )
        assert first.status_code == 200 and second.status_code == 200

        r = await client.get(f"/v1/shot/{correlation_id}", headers=_headers(tenant_id))
        async with build_engine(app.state.deps.settings.database_url).begin() as conn:
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM shot_runs WHERE correlation_id = :c"),
                    {"c": correlation_id},
                )
            ).scalar_one()
        assert count == 1
        assert r.status_code == 200


class TestAnnotationRouting:
    async def test_an_abstention_is_queued_as_shot(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        """FR-M09-08: a near-miss is the sample worth labelling."""
        app, client = app_client
        person_id = await _seed_consented_person(_migrated_database)
        correlation_id = _corr()
        # High, still hands read equally as a defensive push or the top of a
        # pull — a genuinely ambiguous stroke that abstains on the top-2 margin.
        app.state.deps.pose_source.set_payload(correlation_id, _ambiguous_pose())

        r = await client.post(
            "/internal/shot/classify",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )
        assert r.status_code == 200, r.text
        # The flat pose is engineered to abstain deterministically.
        assert r.json()["shot_class"] == "unclassified"
        rows = await _queue_rows(_migrated_database, correlation_id)
        assert rows == [(MODALITY_SHOT, "abstained")]

    async def test_a_confident_classification_is_not_queued(
        self,
        app_client: tuple[FastAPI, httpx.AsyncClient],
        tenant_id: uuid.UUID,
        _migrated_database: str,
    ) -> None:
        app, client = app_client
        person_id = await _seed_consented_person(_migrated_database)
        correlation_id = _corr()
        _seed_full(app, correlation_id)

        r = await client.post(
            "/internal/shot/classify",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )
        assert r.status_code == 200, r.text
        # Full fusion on a clean driving stroke classifies confidently.
        assert r.json()["quality"] == "ok"
        assert await _queue_rows(_migrated_database, correlation_id) == []


class TestReadRun:
    async def test_get_returns_the_summary(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed_full(app, correlation_id)
        await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/shot/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["correlation_id"] == correlation_id

    async def test_other_tenant_cannot_read_the_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        app, client = app_client
        correlation_id = _corr()
        _seed_full(app, correlation_id)
        await client.post(
            "/internal/shot/classify", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/shot/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_shot_classified_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M09-06: schema + correlation_id, with M10's decision fields."""
        app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m09-sc-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_SHOT_CLASSIFIED, group_id=group)
            correlation_id = _corr()
            _seed_full(app, correlation_id)

            r = await client.post(
                "/internal/shot/classify", headers=_headers(tenant_id), json=_body(correlation_id)
            )
            assert r.status_code == 200, r.text

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if env.payload.get("correlation_id") == correlation_id:
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.tenant_id == tenant_id
            assert env.payload["shot_class"] == r.json()["shot_class"]
            assert env.payload["phase_method"] == "standard"
            assert "phase_boundaries" in env.payload
            assert env.payload["signals_used"] == ["pose", "bat", "ball"]
        finally:
            await bus.stop()


class TestConsumer:
    async def test_pose_keypoints_drives_a_shot_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The production trigger: pose.keypoints in, a persisted run out."""
        app, client = app_client
        consumer = build_shot_consumer(app.state.deps, idempotency_store=InMemoryIdempotencyStore())
        correlation_id = _corr()
        _seed_full(app, correlation_id)
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.1.0",
            idempotency_key=f"{TOPIC_POSE_KEYPOINTS}:{correlation_id}",
            payload={"person_id": None, "camera_angle": "side_on"},
        )

        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True and first.success is True
        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False  # deduped

        r = await client.get(f"/v1/shot/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text


def _ambiguous_pose(frames: int = 20) -> str:
    """Hands held high and still — reads equally as a defensive push or the top
    of a pull, so the classifier's top-2 are near-tied and it abstains on the
    margin condition (not merely on low confidence)."""
    frame_list = []
    for i in range(frames):
        y = 0.8 + 0.02 * math.sin(i)
        frame_list.append(
            [
                {"joint": "left_wrist", "x": 0.0, "y": y, "confidence": 0.9},
                {"joint": "right_wrist", "x": 0.02, "y": y, "confidence": 0.9},
                {"joint": "left_hip", "x": 0.0, "y": 0.9, "confidence": 0.9},
                {"joint": "right_hip", "x": 0.0, "y": 0.9, "confidence": 0.9},
                {"joint": "left_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
                {"joint": "right_ankle", "x": 0.0, "y": 0.0, "confidence": 0.9},
            ]
        )
    return json.dumps({"schema": "pose.keypoints/1.1", "frames": frame_list})
