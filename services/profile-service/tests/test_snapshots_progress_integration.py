"""DNA snapshots + progress trends (M04 Step 4, AC-M04-04, FR-M04-07/08).

Covers:
- M16 takes a versioned snapshot of the current DNA; version increments.
- Snapshot payload captures the current trait values.
- Snapshot reads are consent-scoped; unknown version 404s.
- A period-scoped trend returns the latest value per bucket.
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
from profile_service.routes import DNA_WRITER_ROLE

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


async def _profile_id_for(db: str, person_id: uuid.UUID) -> uuid.UUID:
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            row = (
                await s.execute(
                    text("SELECT id FROM player_profiles WHERE person_id = :p"),
                    {"p": person_id},
                )
            ).one()
        return uuid.UUID(str(row[0]))
    finally:
        await engine.dispose()


async def _write_history_at(
    db: str, *, profile_id: uuid.UUID, trait_key: str, value: str, at: datetime
) -> None:
    """Insert a history row at a controlled timestamp (for trend bucketing)."""
    engine = build_engine(db)
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as s:
            await s.execute(
                text(
                    "INSERT INTO dna_trait_history "
                    "  (id, profile_id, trait_key, value, provenance, snapshot_at) "
                    "VALUES (:id, :pid, :k, :v, 'modelled', :at)"
                ),
                {"id": uuid.uuid4(), "pid": profile_id, "k": trait_key, "v": value, "at": at},
            )
    finally:
        await engine.dispose()


async def _seed_person_with_profile(client: httpx.AsyncClient, db: str) -> uuid.UUID:
    pid = await _seed_person(db)
    r = await client.post(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={})
    assert r.status_code == 201, r.text
    return pid


async def _write_trait(client: httpx.AsyncClient, pid: uuid.UUID, key: str, value: str) -> None:
    r = await client.post(
        f"/v1/players/{pid}/dna",
        headers=_m16(),
        json={"updates": [{"trait_key": key, "value": value, "provenance": "modelled"}]},
    )
    assert r.status_code == 201, r.text


class TestSnapshots:
    async def test_m16_takes_versioned_snapshot(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _write_trait(client, pid, "trait.aggression", "0.8")
        await _write_trait(client, pid, "trait.balance", "0.6")

        s1 = await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_m16())
        assert s1.status_code == 201, s1.text
        assert s1.json()["version"] == 1
        assert s1.json()["trait_count"] == 2

        # A second snapshot increments the version.
        await _write_trait(client, pid, "trait.power", "0.9")
        s2 = await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_m16())
        assert s2.json()["version"] == 2
        assert s2.json()["trait_count"] == 3

    async def test_non_m16_cannot_snapshot(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_auth(pid, roles.PLAYER))
        assert r.status_code == 403

    async def test_snapshot_detail_captures_values(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _write_trait(client, pid, "trait.timing", "0.55")
        await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_m16())

        detail = await client.get(
            f"/v1/players/{pid}/dna/snapshots/1", headers=_auth(pid, roles.PLAYER)
        )
        assert detail.status_code == 200, detail.text
        payload = detail.json()["payload"]
        assert payload["trait.timing"]["value"] == "0.55"

    async def test_snapshot_list_and_unknown_version_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _write_trait(client, pid, "trait.footwork", "0.7")
        await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_m16())

        lst = await client.get(f"/v1/players/{pid}/dna/snapshots", headers=_auth(pid, roles.PLAYER))
        assert lst.status_code == 200
        assert [s["version"] for s in lst.json()] == [1]

        missing = await client.get(
            f"/v1/players/{pid}/dna/snapshots/99", headers=_auth(pid, roles.PLAYER)
        )
        assert missing.status_code == 404

    async def test_snapshot_read_consent_scoped(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await _write_trait(client, pid, "trait.consistency", "0.5")
        await client.post(f"/v1/players/{pid}/dna/snapshots", headers=_m16())

        stranger = await _seed_person(_migrated_database)
        r = await client.get(
            f"/v1/players/{pid}/dna/snapshots", headers=_auth(stranger, roles.COACH)
        )
        assert r.status_code == 403


class TestProgressTrend:
    async def test_monthly_trend_latest_per_bucket(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """Two months of history -> one point per month, holding the latest."""
        pid = await _seed_person_with_profile(client, _migrated_database)
        profile_id = await _profile_id_for(_migrated_database, pid)

        # January: two writes; the later (0.40) should win the bucket.
        await _write_history_at(
            _migrated_database,
            profile_id=profile_id,
            trait_key="trait.aggression",
            value="0.30",
            at=datetime(2026, 1, 5, tzinfo=UTC),
        )
        await _write_history_at(
            _migrated_database,
            profile_id=profile_id,
            trait_key="trait.aggression",
            value="0.40",
            at=datetime(2026, 1, 20, tzinfo=UTC),
        )
        # February: one write.
        await _write_history_at(
            _migrated_database,
            profile_id=profile_id,
            trait_key="trait.aggression",
            value="0.65",
            at=datetime(2026, 2, 10, tzinfo=UTC),
        )

        r = await client.get(
            f"/v1/players/{pid}/progress",
            params={"trait_key": "trait.aggression", "period": "monthly"},
            headers=_auth(pid, roles.PLAYER),
        )
        assert r.status_code == 200, r.text
        points = r.json()
        assert len(points) == 2
        assert points[0]["value"] == "0.40"  # Jan latest
        assert points[1]["value"] == "0.65"  # Feb

    async def test_trend_consent_scoped(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        stranger = await _seed_person(_migrated_database)
        r = await client.get(
            f"/v1/players/{pid}/progress",
            params={"trait_key": "trait.timing", "period": "weekly"},
            headers=_auth(stranger, roles.COACH),
        )
        assert r.status_code == 403

    async def test_invalid_period_rejected(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.get(
            f"/v1/players/{pid}/progress",
            params={"trait_key": "trait.timing", "period": "daily"},
            headers=_auth(pid, roles.PLAYER),
        )
        assert r.status_code == 400
