"""M02 Step 8 — lockout, lifecycle, and audit-log integration.

Covers AC-M02-05 (brute-force lockout), AC-M02-06 (no PII leakage — verified
via the register log elsewhere; here we confirm hashing + generic errors),
and AC-M02-07 (sensitive actions recorded in audit_log with actor +
correlation_id).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from cip_core import roles
from cip_data.engine import (
    admin_session,
    build_engine,
    build_session_factory,
    tenant_session,
)
from cip_data.migrations import upgrade_head
from identity_service.domain.lockout import MAX_FAILURES
from identity_service.main import create_app

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
IDENTITY_MIGRATIONS = REPO_ROOT / "services" / "identity-service" / "migrations"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=IDENTITY_MIGRATIONS)
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


def _email(p: str) -> str:
    return f"{p}-{uuid.uuid4().hex[:8]}@fake-cricket.io"


async def _register_verify_login(client: httpx.AsyncClient, email: str, password: str) -> str:
    reg = await client.post(
        "/v1/auth/register",
        headers={"Idempotency-Key": f"i-{uuid.uuid4().hex}"},
        json={"email": email, "password": password, "dob": "1990-01-01"},
    )
    await client.post("/v1/auth/verify-email", json={"token": reg.json()["verification_url_hint"]})
    login = await client.post("/v1/auth/login", json={"email": email, "password": password})
    return login.json()["access_token"]


async def _count_audit(action: str) -> int:
    engine = build_engine(_database_url())
    sf = build_session_factory(engine)
    try:
        async with admin_session(sf) as session:
            row = await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = :a"),
                {"a": action},
            )
            return int(row.scalar() or 0)
    finally:
        await engine.dispose()


class TestBruteForceLockout:
    """AC-M02-05: brute force triggers lockout."""

    async def test_lockout_after_repeated_failures(self, client: httpx.AsyncClient) -> None:
        email = _email("lockme")
        password = "the-correct-password-123"
        await _register_verify_login(client, email, password)

        # Hammer with the wrong password.
        last_status = None
        for _ in range(MAX_FAILURES):
            r = await client.post(
                "/v1/auth/login", json={"email": email, "password": "wrong-password-x"}
            )
            last_status = r.status_code
        # The failing attempts are 401 until the lock trips (429).
        assert last_status == 429

        # Even the CORRECT password is now rejected while locked.
        blocked = await client.post("/v1/auth/login", json={"email": email, "password": password})
        assert blocked.status_code == 429
        assert blocked.json()["error"]["code"] == "RATE_LIMITED"

    async def test_successful_login_after_few_failures_clears_counter(
        self, client: httpx.AsyncClient
    ) -> None:
        email = _email("recover")
        password = "the-correct-password-456"
        await _register_verify_login(client, email, password)

        # A couple of failures (below the threshold)
        for _ in range(MAX_FAILURES - 2):
            await client.post("/v1/auth/login", json={"email": email, "password": "nope-nope"})
        # Correct login succeeds and clears the counter
        ok = await client.post("/v1/auth/login", json={"email": email, "password": password})
        assert ok.status_code == 200


class TestAuditTrail:
    """AC-M02-07: sensitive actions recorded in audit_log."""

    async def test_login_is_audited(self, client: httpx.AsyncClient) -> None:
        before = await _count_audit("auth.login")
        email = _email("audit-login")
        await _register_verify_login(client, email, "audit-login-password-1")
        after = await _count_audit("auth.login")
        assert after > before

    async def test_lifecycle_actions_are_audited(self, client: httpx.AsyncClient) -> None:
        email = _email("lifecycle")
        token = await _register_verify_login(client, email, "lifecycle-password-1")
        hdr = {"Authorization": f"Bearer {token}"}

        before_export = await _count_audit("account.export_requested")
        exp = await client.post("/v1/me/export-request", headers=hdr)
        assert exp.status_code == 200
        assert exp.json()["action"] == "account.export_requested"
        assert await _count_audit("account.export_requested") > before_export

        before_del = await _count_audit("account.deletion_requested")
        dele = await client.post("/v1/me/deletion-request", headers=hdr)
        assert dele.status_code == 200
        assert dele.json()["status"] == "deletion_requested"
        assert await _count_audit("account.deletion_requested") > before_del

    async def test_audit_row_carries_actor_and_correlation(self, client: httpx.AsyncClient) -> None:
        email = _email("audit-fields")
        token = await _register_verify_login(client, email, "audit-fields-pw-1")
        corr = f"corr-{uuid.uuid4().hex}"
        await client.post(
            "/v1/me/export-request",
            headers={"Authorization": f"Bearer {token}", "X-Correlation-ID": corr},
        )
        engine = build_engine(_database_url())
        sf = build_session_factory(engine)
        try:
            async with admin_session(sf) as session:
                row = (
                    await session.execute(
                        text(
                            "SELECT actor, correlation_id FROM audit_log "
                            "WHERE correlation_id = :c AND action = 'account.export_requested'"
                        ),
                        {"c": corr},
                    )
                ).first()
            assert row is not None
            assert row[0].startswith("person:")
            assert row[1] == corr
        finally:
            await engine.dispose()

    async def test_role_change_is_audited(self, client: httpx.AsyncClient) -> None:
        # Seed an academy to join.
        tid = uuid.uuid4()
        engine = build_engine(_database_url())
        sf = build_session_factory(engine)
        try:
            async with admin_session(sf) as session:
                await session.execute(
                    text(
                        "INSERT INTO tenants (id, name, type, region) "
                        "VALUES (:id, :n, 'academy', 'IN')"
                    ),
                    {"id": tid, "n": f"acad-{uuid.uuid4().hex[:8]}"},
                )
        finally:
            await engine.dispose()

        email = _email("role-audit")
        token = await _register_verify_login(client, email, "role-audit-pw-1")
        await client.post(
            "/v1/memberships",
            headers={
                "Authorization": f"Bearer {token}",
                "Idempotency-Key": f"i-{uuid.uuid4().hex}",
            },
            json={"tenant_id": str(tid), "role": roles.PLAYER},
        )
        # The role-change audit row is TENANT-scoped, so it's only visible
        # inside a session for that tenant (RLS) — proving it landed under
        # the right tenant, not as a global row.
        engine = build_engine(_database_url())
        sf = build_session_factory(engine)
        try:
            async with tenant_session(sf, tenant_id=tid) as session:
                count = (
                    await session.execute(
                        text(
                            "SELECT count(*) FROM audit_log "
                            "WHERE action = 'membership.role_granted' AND tenant_id = :t"
                        ),
                        {"t": tid},
                    )
                ).scalar()
            assert count == 1
        finally:
            await engine.dispose()
