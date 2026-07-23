"""Cricket DNA store — M16-only write, append-only history (M04 Step 3, AC-M04-03).

Covers:
- Only the DNA-engine service role can write traits; players/coaches/admins 401/403.
- A write UPSERTs the current value AND appends history.
- History is append-only + reconstructable to any prior point (NFR-M04-02).
- Provenance + confidence are carried on the write (FR-M04-04).
- DNA reads are consent-scoped (self allowed; unconsented coach denied).
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


def _m16_auth() -> dict[str, str]:
    """A token carrying the DNA-engine service role (M16)."""
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


async def _seed_person_with_profile(client: httpx.AsyncClient, db: str) -> uuid.UUID:
    pid = await _seed_person(db)
    r = await client.post(f"/v1/players/{pid}/profile", headers=_auth(pid, roles.PLAYER), json={})
    assert r.status_code == 201, r.text
    return pid


class TestWriteAuthorization:
    async def test_player_cannot_write_traits(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/dna",
            headers=_auth(pid, roles.PLAYER),
            json={
                "updates": [
                    {"trait_key": "trait.aggression", "value": "0.8", "provenance": "modelled"}
                ]
            },
        )
        assert r.status_code == 403

    async def test_academy_admin_cannot_write_traits(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/dna",
            headers=_auth(uuid.uuid4(), roles.ACADEMY_ADMIN),
            json={
                "updates": [
                    {"trait_key": "trait.balance", "value": "0.6", "provenance": "modelled"}
                ]
            },
        )
        assert r.status_code == 403

    async def test_unauthenticated_cannot_write(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/dna",
            json={
                "updates": [{"trait_key": "trait.power", "value": "0.5", "provenance": "modelled"}]
            },
        )
        assert r.status_code == 401

    async def test_m16_can_write(self, client: httpx.AsyncClient, _migrated_database: str) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        r = await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16_auth(),
            json={
                "updates": [
                    {
                        "trait_key": "trait.aggression",
                        "value": "0.80",
                        "provenance": "modelled",
                        "confidence": 0.9,
                        "source_ref": "report:abc",
                    }
                ]
            },
        )
        assert r.status_code == 201, r.text
        assert r.json()["written"] == 1

    async def test_write_to_missing_profile_404(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person(_migrated_database)  # no profile
        r = await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16_auth(),
            json={
                "updates": [{"trait_key": "trait.timing", "value": "0.7", "provenance": "modelled"}]
            },
        )
        assert r.status_code == 404


class TestCurrentAndHistory:
    async def test_write_upserts_current_and_appends_history(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)

        # Two successive writes of the SAME trait.
        for val, conf in (("0.50", 0.7), ("0.75", 0.85)):
            r = await client.post(
                f"/v1/players/{pid}/dna",
                headers=_m16_auth(),
                json={
                    "updates": [
                        {
                            "trait_key": "trait.timing",
                            "value": val,
                            "provenance": "modelled",
                            "confidence": conf,
                        }
                    ]
                },
            )
            assert r.status_code == 201, r.text

        # Current DNA has exactly one row for the trait, holding the latest value.
        cur = await client.get(f"/v1/players/{pid}/dna", headers=_auth(pid, roles.PLAYER))
        assert cur.status_code == 200, cur.text
        rows = cur.json()
        timing = [t for t in rows if t["trait_key"] == "trait.timing"]
        assert len(timing) == 1
        assert timing[0]["value"] == "0.75"
        assert timing[0]["confidence"] == 0.85

        # History has BOTH writes (append-only).
        hist = await client.get(
            f"/v1/players/{pid}/dna/history?trait_key=trait.timing",
            headers=_auth(pid, roles.PLAYER),
        )
        assert hist.status_code == 200
        values = [h["value"] for h in hist.json()]
        assert values == ["0.50", "0.75"]  # ordered by snapshot_at

    async def test_reconstruct_at_prior_point(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        """NFR-M04-02: reconstruct a trait's value as of a past instant."""
        pid = await _seed_person_with_profile(client, _migrated_database)

        await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16_auth(),
            json={
                "updates": [{"trait_key": "trait.power", "value": "0.40", "provenance": "modelled"}]
            },
        )
        # Capture a cut point between the two writes.
        cut = datetime.now(UTC)
        # Ensure the second write's snapshot_at is strictly after the cut.
        import asyncio

        await asyncio.sleep(0.01)
        await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16_auth(),
            json={
                "updates": [{"trait_key": "trait.power", "value": "0.90", "provenance": "modelled"}]
            },
        )

        # Current shows the latest.
        cur = await client.get(f"/v1/players/{pid}/dna", headers=_auth(pid, roles.PLAYER))
        power_now = next(t for t in cur.json() if t["trait_key"] == "trait.power")
        assert power_now["value"] == "0.90"

        # Reconstruction as of the cut point shows the earlier value.
        # Pass via params so the '+' in the tz offset is percent-encoded.
        recon = await client.get(
            f"/v1/players/{pid}/dna/history",
            params={"at": cut.isoformat()},
            headers=_auth(pid, roles.PLAYER),
        )
        assert recon.status_code == 200, recon.text
        power_then = [t for t in recon.json() if t["trait_key"] == "trait.power"]
        assert len(power_then) == 1
        assert power_then[0]["value"] == "0.40"


class TestDNAReadConsent:
    async def test_unconsented_coach_denied_dna(
        self, client: httpx.AsyncClient, _migrated_database: str
    ) -> None:
        pid = await _seed_person_with_profile(client, _migrated_database)
        await client.post(
            f"/v1/players/{pid}/dna",
            headers=_m16_auth(),
            json={
                "updates": [
                    {"trait_key": "trait.footwork", "value": "0.6", "provenance": "modelled"}
                ]
            },
        )
        coach = await _seed_person(_migrated_database)
        r = await client.get(f"/v1/players/{pid}/dna", headers=_auth(coach, roles.COACH))
        assert r.status_code == 403
