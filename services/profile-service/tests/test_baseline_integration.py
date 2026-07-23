"""Personal baseline observe + M15 read (M04 Step 5, AC-M04-05, FR-M04-06).

Covers:
- Only the metrics-writer service role records observations; others 403.
- Successive observations grow the distribution (count/mean move).
- The served baseline is in the CIP-STD metric shape (metric_key + distribution).
- Reads are gated on the subject's processing consent (M15 internal path).
- Invalid metric ids are rejected (must be CIP-STD, e.g. BM-01).
"""

from __future__ import annotations

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
from profile_service.main import create_app
from profile_service.routes import BASELINE_WRITER_ROLE

pytestmark = pytest.mark.integration

TEST_JWT_SECRET = "test-jwt-signing-key-do-not-use-in-any-real-environment-42"


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


def _metrics_writer() -> dict[str, str]:
    return _auth(uuid.uuid4(), BASELINE_WRITER_ROLE)


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


async def _seed_consent(db: str, *, person_id: uuid.UUID, consent_type: str) -> None:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO consents (id, person_id, type, granted_by, scope) "
                    "VALUES (:id, :p, :ty, :p, '{}'::jsonb)"
                ),
                {"id": uuid.uuid4(), "p": person_id, "ty": consent_type},
            )
    finally:
        await engine.dispose()


async def _seed_person_with_profile(client: httpx.AsyncClient, db: str) -> uuid.UUID:
    pid = await _seed_person(db)
    r = await client.post(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={})
    assert r.status_code == 201, r.text
    return pid


async def _observe(
    client: httpx.AsyncClient, pid: uuid.UUID, metric: str, value: float
) -> httpx.Response:
    return await client.post(
        f"/v1/players/{pid}/baseline",
        headers=_metrics_writer(),
        json={"metric_key": metric, "value": value},
    )


class TestObserveAuthorization:
    async def test_player_cannot_observe(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/baseline",
            headers=_auth(pid, roles.PLAYER),
            json={"metric_key": "BM-01", "value": 7.0},
        )
        assert r.status_code == 403

    async def test_metrics_writer_can_observe(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await _observe(client, pid, "BM-01", 7.0)
        assert r.status_code == 201, r.text
        assert r.json()["metric_key"] == "BM-01"
        assert r.json()["distribution"]["count"] == 1

    async def test_invalid_metric_id_rejected(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/baseline",
            headers=_metrics_writer(),
            json={"metric_key": "aggression", "value": 1.0},
        )
        assert r.status_code == 400

    async def test_observe_missing_profile_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)  # no profile
        r = await _observe(client, pid, "BM-01", 5.0)
        assert r.status_code == 404


class TestDistributionGrows:
    async def test_successive_observations_update_distribution(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        for v in (6.0, 8.0, 10.0):
            r = await _observe(client, pid, "BM-02", v)
            assert r.status_code == 201, r.text

        last = r.json()["distribution"]
        assert last["count"] == 3
        assert last["mean"] == pytest.approx(8.0)
        assert last["min"] == 6.0
        assert last["max"] == 10.0


class TestM15Read:
    async def test_read_baseline_cip_std_shape(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _seed_consent(_migrated_database, person_id=pid, consent_type="processing")
        await _observe(client, pid, "BM-04", 22.0)
        await _observe(client, pid, "BM-04", 28.0)

        reader = await _seed_person(_migrated_database)
        one = await client.get(
            f"/v1/players/{pid}/baseline/BM-04", headers=_auth(reader, roles.PLAYER)
        )
        assert one.status_code == 200, one.text
        body = one.json()
        assert body["metric_key"] == "BM-04"
        # CIP-STD distribution shape.
        for key in ("count", "mean", "stddev", "min", "max", "p25", "p50", "p75"):
            assert key in body["distribution"]
        assert body["distribution"]["count"] == 2

        listing = await client.get(
            f"/v1/players/{pid}/baseline", headers=_auth(reader, roles.PLAYER)
        )
        assert listing.status_code == 200
        assert [b["metric_key"] for b in listing.json()] == ["BM-04"]

    async def test_read_denied_without_processing_consent(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _observe(client, pid, "BM-05", 3.0)  # no processing consent seeded
        reader = await _seed_person(_migrated_database)
        r = await client.get(f"/v1/players/{pid}/baseline", headers=_auth(reader, roles.PLAYER))
        assert r.status_code == 403

    async def test_read_unknown_metric_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _seed_consent(_migrated_database, person_id=pid, consent_type="processing")
        reader = await _seed_person(_migrated_database)
        r = await client.get(
            f"/v1/players/{pid}/baseline/BM-99", headers=_auth(reader, roles.PLAYER)
        )
        assert r.status_code == 404
