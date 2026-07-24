"""Pose compute + persist + publish (M06 Steps 2 + 6).

Covers:
- AC-M06-01 clean side-on clip -> keypoints for every frame, per-joint confidence
- AC-M06-02 two comparable people -> rejected, no guessed subject
- AC-M06-03 2D keypoints always present; depth carries depth_estimated
- AC-M06-04 low-confidence clip -> provisional, never silently downgraded
- AC-M06-05 pose.keypoints published with schema + quality summary +
  correlation_id, and re-delivery is idempotent
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

from cip_core import roles
from cip_events import EventEnvelope, InMemoryIdempotencyStore, KafkaEventBus
from pose_service.domain.artefact import artefact_key
from pose_service.main import create_app
from pose_service.service import (
    TOPIC_POSE_KEYPOINTS,
    TOPIC_VIDEO_NORMALIZED,
    build_pose_consumer,
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


def _body(correlation_id: str, person_id: uuid.UUID | None = None) -> dict[str, object]:
    """A video.normalized payload as M05 publishes it."""
    return {
        "correlation_id": correlation_id,
        "normalized_ref": f"tenant/x/normalized/{correlation_id}.mp4",
        "person_id": str(person_id or uuid.uuid4()),
        "camera_angle": "side_on",
        "spatial_confidence": "high",
        "quality_flags": [{"code": "lighting_soft", "severity": "soft"}],
    }


def _corr() -> str:
    return f"m06-{uuid.uuid4().hex[:12]}"


class TestCompute:
    async def test_clean_clip_produces_keypoints_for_every_frame(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M06-01: keypoints for every frame, each joint carrying a confidence."""
        app, client = app_client
        correlation_id = _corr()

        r = await client.post(
            "/internal/pose/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["subject_status"] == "tracked"
        assert run["quality"] == "ok"
        assert run["frame_count"] == 30
        assert run["model_version"] == "fake-pose-v1"
        assert run["depth_estimated"] is True
        assert run["mean_confidence"] is not None and run["mean_confidence"] > 0.5

        # The artefact holds the actual keypoint sequence (FR-M06-09).
        key = artefact_key(tenant_id=tenant_id, correlation_id=correlation_id)
        assert run["artefact_ref"] == key
        raw = await app.state.deps.artefact_store.load(key)
        assert raw is not None
        payload = json.loads(raw)
        assert payload["schema"] == "pose.keypoints/1.0"
        assert len(payload["frames"]) == 30
        for frame in payload["frames"]:
            assert len(frame) == 17  # canonical joint set
            for kp in frame:
                assert 0.0 <= kp["confidence"] <= 1.0
                # AC-M06-03: 2D is always there; z only appears with its flag.
                assert "x" in kp and "y" in kp
                assert "z" not in kp or kp["depth_estimated"] is True

    async def test_multi_subject_clip_is_rejected(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M06-02: two comparable people -> rejection, not a guess."""
        app, client = app_client
        app.state.deps.model.patch(persons=2, comparable=True)
        correlation_id = _corr()

        r = await client.post(
            "/internal/pose/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["subject_status"] == "multi_subject_ambiguous"
        assert run["quality"] == "rejected"
        assert run["artefact_ref"] is None  # nothing guessed, nothing stored
        assert run["mean_confidence"] is None

    async def test_low_confidence_clip_is_provisional(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M06-04: weak signal is labelled provisional, output still produced."""
        app, client = app_client
        app.state.deps.model.patch(base_confidence=0.35)
        correlation_id = _corr()

        r = await client.post(
            "/internal/pose/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        assert r.status_code == 200, r.text
        run = r.json()
        assert run["subject_status"] == "tracked"
        assert run["quality"] == "provisional"
        assert run["artefact_ref"] is not None  # provisional output is still delivered

    async def test_recompute_is_idempotent(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M06-05: same correlation_id -> one row, one artefact."""
        app, client = app_client
        correlation_id = _corr()
        body = _body(correlation_id)

        first = await client.post("/internal/pose/compute", headers=_headers(tenant_id), json=body)
        second = await client.post("/internal/pose/compute", headers=_headers(tenant_id), json=body)
        assert first.status_code == 200 and second.status_code == 200
        assert first.json()["correlation_id"] == second.json()["correlation_id"]
        assert first.json()["artefact_ref"] == second.json()["artefact_ref"]
        # One artefact key, and one DB row (the upsert conflicts on correlation).
        keys = [k for k in app.state.deps.artefact_store.objects if correlation_id in k]
        assert len(keys) == 1

        listed = await client.get(f"/v1/pose/{correlation_id}", headers=_headers(tenant_id))
        assert listed.status_code == 200
        assert listed.json()["frame_count"] == 30


class TestReadRun:
    async def test_get_returns_run_summary(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        correlation_id = _corr()
        person_id = uuid.uuid4()
        await client.post(
            "/internal/pose/compute",
            headers=_headers(tenant_id),
            json=_body(correlation_id, person_id),
        )

        r = await client.get(f"/v1/pose/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["person_id"] == str(person_id)
        assert r.json()["quality"] == "ok"

    async def test_unknown_correlation_is_404(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        _app, client = app_client
        r = await client.get(f"/v1/pose/{_corr()}", headers=_headers(tenant_id))
        assert r.status_code == 404

    async def test_other_tenant_cannot_read_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """RLS: a run belongs to the tenant that produced it."""
        _app, client = app_client
        correlation_id = _corr()
        await client.post(
            "/internal/pose/compute", headers=_headers(tenant_id), json=_body(correlation_id)
        )
        r = await client.get(f"/v1/pose/{correlation_id}", headers=_headers(uuid.uuid4()))
        assert r.status_code == 404


class TestPublish:
    async def test_pose_keypoints_is_published(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """AC-M06-05: artefact ref + summary + quality, with M05 context carried."""
        _app, client = app_client
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m06-kp-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_POSE_KEYPOINTS, group_id=group)
            correlation_id = _corr()

            r = await client.post(
                "/internal/pose/compute", headers=_headers(tenant_id), json=_body(correlation_id)
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
            assert env.payload["quality"] == "ok"
            assert env.payload["subject_status"] == "tracked"
            assert env.payload["frame_count"] == 30
            assert env.payload["model_version"] == "fake-pose-v1"
            assert env.payload["depth_estimated"] is True
            # M05 calibration + quality context propagates downstream (FR-M06-08).
            assert env.payload["camera_angle"] == "side_on"
            assert env.payload["spatial_confidence"] == "high"
            assert env.payload["quality_flags"][0]["code"] == "lighting_soft"
        finally:
            await bus.stop()


class TestConsumer:
    async def test_video_normalized_drives_a_pose_run(
        self, app_client: tuple[FastAPI, httpx.AsyncClient], tenant_id: uuid.UUID
    ) -> None:
        """The production trigger: an event in, a persisted run out."""
        app, client = app_client
        consumer = build_pose_consumer(app.state.deps, idempotency_store=InMemoryIdempotencyStore())
        correlation_id = _corr()
        person_id = uuid.uuid4()
        envelope = EventEnvelope(
            correlation_id=correlation_id,
            tenant_id=tenant_id,
            schema_version="1.0.0",
            idempotency_key=f"{TOPIC_VIDEO_NORMALIZED}:{correlation_id}",
            payload=_body(correlation_id, person_id),
        )

        first = await consumer.process_one(envelope)
        assert first.handler_invoked is True
        assert first.success is True

        # Re-delivery is deduped by the consumer, and the run is unchanged.
        second = await consumer.process_one(envelope)
        assert second.handler_invoked is False
        assert second.attempts == 0

        r = await client.get(f"/v1/pose/{correlation_id}", headers=_headers(tenant_id))
        assert r.status_code == 200, r.text
        assert r.json()["person_id"] == str(person_id)
        assert r.json()["subject_status"] == "tracked"
        keys = [k for k in app.state.deps.artefact_store.objects if correlation_id in k]
        assert len(keys) == 1
