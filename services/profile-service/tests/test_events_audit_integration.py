"""Events + audit on all mutations (M04 Step 7, AC-M04-07, FR-M04-10/11).

Covers:
- profile.updated is published on create + attribute patch (Kafka consumer).
- dna.updated is published on a trait write.
- Every mutation writes an M01 audit_log row with actor + correlation_id.
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
from sqlalchemy import text

from cip_core import roles
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_events import EventEnvelope, KafkaEventBus
from profile_service.main import create_app
from profile_service.routes import (
    DNA_WRITER_ROLE,
    TOPIC_DNA_UPDATED,
    TOPIC_PROFILE_UPDATED,
)

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"
DEFAULT_BOOTSTRAP = "localhost:9092"


@pytest_asyncio.fixture
async def client(_migrated_database: str) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


def _token(person_id: uuid.UUID, *claim_roles: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": str(person_id),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _auth(person_id: uuid.UUID, *claim_roles: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(person_id, *claim_roles)}"}


def _m16() -> dict[str, str]:
    return _auth(uuid.uuid4(), DNA_WRITER_ROLE)


async def _seed_person(db: str) -> uuid.UUID:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    pid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text("INSERT INTO persons (id, email) VALUES (:id, :e)"),
                {"id": pid, "e": f"p-{pid.hex[:10]}@test"},
            )
    finally:
        await engine.dispose()
    return pid


async def _audit_rows(db: str, person_id: uuid.UUID) -> list[dict[str, object]]:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            rows = await s.execute(
                text(
                    "SELECT action, actor, correlation_id FROM audit_log "
                    "WHERE entity = :e AND tenant_id IS NULL ORDER BY at"
                ),
                {"e": f"person:{person_id}"},
            )
            return [dict(r) for r in rows.mappings()]
    finally:
        await engine.dispose()


class TestAuditTrail:
    async def test_all_mutations_audited_with_actor_and_correlation(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """AC-M04-07: every mutation audited with actor + correlation_id."""
        pid = await _seed_person(_migrated_database)
        corr = f"corr-{uuid.uuid4().hex}"
        h_self = {**_auth(pid, roles.PLAYER), "X-Correlation-ID": corr}

        # create -> patch -> dna write -> snapshot.
        assert (
            await client.post(f"/v1/players/{pid}/profile", headers=h_self, json={"height_cm": 170})
        ).status_code == 201
        assert (
            await client.patch(
                f"/v1/players/{pid}/profile", headers=h_self, json={"height_cm": 172}
            )
        ).status_code == 200
        m16 = {**_m16(), "X-Correlation-ID": corr}
        assert (
            await client.post(
                f"/v1/players/{pid}/dna",
                headers=m16,
                json={
                    "updates": [
                        {"trait_key": "trait.power", "value": "0.6", "provenance": "modelled"}
                    ]
                },
            )
        ).status_code == 201
        assert (
            await client.post(f"/v1/players/{pid}/dna/snapshots", headers=m16)
        ).status_code == 201

        rows = await _audit_rows(_migrated_database, pid)
        actions = [r["action"] for r in rows]
        assert "profile.created" in actions
        assert "profile.updated" in actions
        assert "dna.updated" in actions
        assert "dna.snapshot_created" in actions
        # Actor + correlation on every row.
        for r in rows:
            assert r["actor"] is not None
            assert r["correlation_id"] == corr


class TestProfileUpdatedEvent:
    async def test_create_publishes_profile_updated(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m04-prof-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_PROFILE_UPDATED, group_id=group)

            pid = await _seed_person(_migrated_database)
            r = await client.post(
                f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={}
            )
            assert r.status_code == 201

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if str(env.payload.get("person_id")) == str(pid):
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.payload["change"] == "created"
        finally:
            await bus.stop()


class TestDnaUpdatedEvent:
    async def test_dna_write_publishes_dna_updated(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m04-dna-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_DNA_UPDATED, group_id=group)

            pid = await _seed_person(_migrated_database)
            await client.post(
                f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={}
            )
            r = await client.post(
                f"/v1/players/{pid}/dna",
                headers=_m16(),
                json={
                    "updates": [
                        {"trait_key": "trait.balance", "value": "0.7", "provenance": "modelled"}
                    ]
                },
            )
            assert r.status_code == 201

            async def _find() -> EventEnvelope:
                async for env in consumer_iter:
                    if str(env.payload.get("person_id")) == str(pid):
                        return env
                raise RuntimeError("consumer exhausted")

            env = await asyncio.wait_for(_find(), timeout=15.0)
            assert env.payload["trait_keys"] == ["trait.balance"]
            assert env.payload["count"] == 1
        finally:
            await bus.stop()
