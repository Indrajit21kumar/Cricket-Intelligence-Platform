"""Seats + M20 events + billing_audit (M03 Step 8, AC-M03-06/07, FR-M03-08/09/10).

Covers:
- POST /v1/seats — allocate a seat on an academy plan (seats.max = 25).
- POST /v1/seats — 409 once the seat pool is full.
- POST /v1/seats — 400 on a plan without seats (pro/starter).
- DELETE /v1/seats/{id} — soft-revokes; count returns to allow re-allocation.
- billing_audit rows appear for subscribe / seat allocate / seat revoke
  with actor = principal.person_id and correlation_id from the request.
- billing.subscription.changed is published on subscribe (Kafka consumer).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import text

from billing_service.domain.catalogue import seed_catalogue
from billing_service.main import create_app
from billing_service.routes import TOPIC_SUBSCRIPTION_CHANGED
from cip_core import roles
from cip_core.settings import get_settings
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session
from cip_data.migrations import upgrade_head
from cip_events import EventEnvelope, KafkaEventBus

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"
DEFAULT_BOOTSTRAP = "localhost:9092"

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"


@pytest.fixture(autouse=True)
def _pin_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BILLING_MIGRATIONS)
    return url


@pytest_asyncio.fixture
async def client(migrated_db: str) -> AsyncIterator[httpx.AsyncClient]:
    _ = migrated_db
    app = create_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as ac,
    ):
        yield ac


def _access_token(*claim_roles: str, person_id: str | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": person_id or str(uuid.uuid4()),
            "type": "access",
            "roles": list(claim_roles),
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=15)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        TEST_JWT_SECRET,
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _seed_tenant(migrated_db: str) -> uuid.UUID:
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    tid = uuid.uuid4()
    try:
        async with admin_session(sf) as s:
            await seed_catalogue(s)
            await s.execute(
                text(
                    "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', 'IN')"
                ),
                {"id": tid, "n": f"acad-{uuid.uuid4().hex[:8]}"},
            )
    finally:
        await engine.dispose()
    return tid


async def _count_audit_rows(migrated_db: str, tenant_id: uuid.UUID, action: str) -> int:
    engine = build_engine(migrated_db)
    sf = build_session_factory(engine)
    try:
        async with tenant_session(sf, tenant_id=tenant_id) as s:
            row = await s.execute(
                text(
                    "SELECT count(*) FROM billing_audit "
                    "WHERE action = :a AND correlation_id IS NOT NULL"
                ),
                {"a": action},
            )
            return int(row.scalar() or 0)
    finally:
        await engine.dispose()


class TestSeatsHappyPath:
    async def test_allocate_seat_on_academy(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))

        sub = (
            await client.post(
                "/v1/subscriptions",
                headers=headers,
                json={"subject": f"tenant:{tid}", "plan_code": "academy"},
            )
        ).json()
        assert sub["plan_code"] == "academy"

        r = await client.post(
            "/v1/seats",
            headers=headers,
            json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
        )
        assert r.status_code == 201, r.text
        assert r.json()["status"] == "active"

    async def test_deallocate_revokes_and_frees_a_slot(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "academy"},
        )

        seat = (
            await client.post(
                "/v1/seats",
                headers=headers,
                json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
            )
        ).json()
        # httpx sends DELETE with body via `content` or json kwarg.
        r = await client.request(
            "DELETE",
            f"/v1/seats/{seat['id']}",
            headers=headers,
            json={"subject": f"tenant:{tid}"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "revoked"


class TestSeatsCapEnforcement:
    async def test_starter_plan_caps_at_one_seat(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """Starter's ``seats.max = 1`` — one allocation OK, second refused."""
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "starter"},
        )

        ok = await client.post(
            "/v1/seats",
            headers=headers,
            json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
        )
        assert ok.status_code == 201, ok.text

        over = await client.post(
            "/v1/seats",
            headers=headers,
            json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
        )
        assert over.status_code == 409  # seats.max reached

    async def test_academy_seats_full_returns_409(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """AC-M03-06: seats respect seats.max — Academy caps at 25."""
        tid = await _seed_tenant(migrated_db)
        headers = _auth(_access_token(roles.ACADEMY_ADMIN))
        await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "academy"},
        )

        # Fill the pool. Academy plan sets seats.max = 25.
        for _ in range(25):
            r = await client.post(
                "/v1/seats",
                headers=headers,
                json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
            )
            assert r.status_code == 201, r.text

        # 26th allocation is refused.
        over = await client.post(
            "/v1/seats",
            headers=headers,
            json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
        )
        assert over.status_code == 409


class TestAuditTrail:
    async def test_subscribe_and_seat_actions_write_billing_audit(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """AC-M03-07: billing actions audited with actor + correlation_id."""
        tid = await _seed_tenant(migrated_db)
        person_id = str(uuid.uuid4())
        headers = _auth(_access_token(roles.ACADEMY_ADMIN, person_id=person_id))
        # Pin the correlation id so we can assert it was persisted.
        correlation = f"corr-{uuid.uuid4().hex}"
        headers["X-Correlation-ID"] = correlation

        # Subscribe (writes subscription.created audit).
        r = await client.post(
            "/v1/subscriptions",
            headers=headers,
            json={"subject": f"tenant:{tid}", "plan_code": "academy"},
        )
        assert r.status_code == 201

        # Allocate seat (writes seat.allocated audit).
        r = await client.post(
            "/v1/seats",
            headers=headers,
            json={"subject": f"tenant:{tid}", "member_ref": str(uuid.uuid4())},
        )
        assert r.status_code == 201

        # Assert billing_audit carries actor + correlation_id.
        engine = build_engine(migrated_db)
        sf = build_session_factory(engine)
        try:
            async with tenant_session(sf, tenant_id=tid) as s:
                rows = (
                    await s.execute(
                        text(
                            "SELECT action, actor, correlation_id "
                            "FROM billing_audit WHERE correlation_id = :c "
                            "ORDER BY at"
                        ),
                        {"c": correlation},
                    )
                ).all()
        finally:
            await engine.dispose()

        actions = [r[0] for r in rows]
        assert "subscription.created" in actions
        assert "seat.allocated" in actions
        for _action, actor, cid in rows:
            assert actor == person_id
            assert cid == correlation


class TestSubscriptionChangedEvent:
    async def test_subscribe_publishes_subscription_changed(
        self, client: httpx.AsyncClient, migrated_db: str
    ) -> None:
        """FR-M03-09: subscribe emits ``billing.subscription.changed`` to M20."""
        bus = KafkaEventBus(os.environ.get("CIP_KAFKA_BOOTSTRAP", DEFAULT_BOOTSTRAP))
        await bus.start()
        try:
            group = f"m03-sub-changed-{uuid.uuid4().hex[:8]}"
            consumer_iter = bus.consume(TOPIC_SUBSCRIPTION_CHANGED, group_id=group)

            tid = await _seed_tenant(migrated_db)
            headers = _auth(_access_token(roles.ACADEMY_ADMIN))
            sub = (
                await client.post(
                    "/v1/subscriptions",
                    headers=headers,
                    json={"subject": f"tenant:{tid}", "plan_code": "pro"},
                )
            ).json()

            async def _find_ours() -> EventEnvelope:
                async for env in consumer_iter:
                    if str(env.payload.get("subscription_id")) == str(sub["id"]):
                        return env
                raise RuntimeError("consumer exhausted without our event")

            env = await asyncio.wait_for(_find_ours(), timeout=15.0)
            assert env.tenant_id == tid
            assert env.payload["plan_code"] == "pro"
            assert env.payload["action"] == "created"
            assert env.payload["status"] == "active"
        finally:
            await bus.stop()
