"""Integration tests for the plan catalogue + entitlement resolution (Step 2)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from billing_service.domain.catalogue import CANONICAL_PLANS, seed_catalogue
from billing_service.domain.entitlements import (
    ANALYSIS_QUOTA_MONTHLY,
    FEATURE_AI_COACH,
    FEATURE_PARTNER_API,
    SEATS_MAX,
    UNLIMITED,
    is_flag_enabled,
    quota_value,
)
from billing_service.domain.plans import get_plan_by_code, resolve_entitlements
from billing_service.main import create_app
from cip_data.engine import admin_session, build_engine, build_session_factory
from cip_data.migrations import upgrade_head

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
BASE_MIGRATIONS = REPO_ROOT / "migrations" / "base"
BILLING_MIGRATIONS = REPO_ROOT / "services" / "billing-service" / "migrations"


def _database_url() -> str:
    return os.environ.get("CIP_DATABASE_URL", "postgresql+asyncpg://cip:cip@localhost:5432/cip")


@pytest.fixture(scope="module")
def migrated_db() -> str:
    url = _database_url()
    upgrade_head(url, migrations_dir=BASE_MIGRATIONS)
    upgrade_head(url, migrations_dir=BILLING_MIGRATIONS)
    return url


@pytest.fixture
def session_factory(migrated_db: str):
    engine = build_engine(migrated_db)
    return build_session_factory(engine)


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


class TestSeeding:
    async def test_seed_is_idempotent(self, session_factory) -> None:
        async with admin_session(session_factory) as s:
            n1 = await seed_catalogue(s)
        async with admin_session(session_factory) as s:
            n2 = await seed_catalogue(s)
        assert n1 == n2 == len(CANONICAL_PLANS)
        # No duplicate plan rows for a code+version.
        async with admin_session(session_factory) as s:
            dupes = (
                await s.execute(
                    text(
                        "SELECT code, count(*) FROM plans GROUP BY code, version "
                        "HAVING count(*) > 1"
                    )
                )
            ).all()
        assert dupes == []


class TestEntitlementResolution:
    async def test_pro_plan_entitlements(self, session_factory) -> None:
        async with admin_session(session_factory) as s:
            await seed_catalogue(s)
            pro = await get_plan_by_code(s, "pro")
            assert pro is not None
            ents = await resolve_entitlements(s, pro["id"])
        assert is_flag_enabled(ents, FEATURE_AI_COACH) is True
        assert quota_value(ents, ANALYSIS_QUOTA_MONTHLY) == UNLIMITED
        assert is_flag_enabled(ents, FEATURE_PARTNER_API) is False

    async def test_starter_plan_is_limited(self, session_factory) -> None:
        async with admin_session(session_factory) as s:
            await seed_catalogue(s)
            starter = await get_plan_by_code(s, "starter")
            ents = await resolve_entitlements(s, starter["id"])
        assert quota_value(ents, ANALYSIS_QUOTA_MONTHLY) == 5
        assert is_flag_enabled(ents, FEATURE_AI_COACH) is False
        assert quota_value(ents, SEATS_MAX) == 1

    async def test_enterprise_has_partner_api(self, session_factory) -> None:
        async with admin_session(session_factory) as s:
            await seed_catalogue(s)
            ent = await get_plan_by_code(s, "enterprise")
            ents = await resolve_entitlements(s, ent["id"])
        assert is_flag_enabled(ents, FEATURE_PARTNER_API) is True
        assert quota_value(ents, SEATS_MAX) == 100


class TestPlansEndpoint:
    async def test_list_plans_returns_catalogue(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/v1/plans")
        assert r.status_code == 200, r.text
        plans = r.json()
        codes = {p["code"] for p in plans}
        assert {"starter", "pro", "academy", "enterprise"} <= codes
        pro = next(p for p in plans if p["code"] == "pro")
        assert pro["entitlements"][FEATURE_AI_COACH] == "true"
        assert pro["price_minor"] == 49900

    async def test_plans_sorted_by_price(self, client: httpx.AsyncClient) -> None:
        r = await client.get("/v1/plans")
        prices = [p["price_minor"] for p in r.json()]
        assert prices == sorted(prices)
