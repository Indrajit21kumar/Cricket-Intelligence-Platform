"""Integration tests for revenue + usage analytics (M20 Step 4, FR-M20-03/04).

These functions aggregate GLOBALLY across every tenant (that's the point --
FR-M20-03/04 ask for platform-wide reporting, not per-tenant), so each test
must use its own disjoint time window to stay isolated from every other
test's real, committed rows in the same shared warehouse. ``_window`` picks
a random far-future slot per call so collisions across tests (or across
concurrent runs) are effectively impossible, unlike anchoring on
``datetime.now(UTC)`` — which every test would do at nearly the same instant.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from admin_service.domain import analytics
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


def _window(hours: int = 1) -> tuple[datetime, datetime, datetime]:
    """A random, disjoint-from-everything-else (start, end, mid) triple."""
    start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=random.randint(0, 500_000_000))
    end = start + timedelta(hours=hours)
    mid = start + timedelta(minutes=hours * 30)
    return start, end, mid


async def _insert_revenue_event(
    sf: async_sessionmaker,
    *,
    topic: str,
    occurred_at: datetime,
    amount_minor: int | None = None,
    currency: str | None = None,
    action: str | None = None,
) -> None:
    payload = {"action": action} if action is not None else {}
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO warehouse.fact_revenue_event "
                "  (id, event_topic, tenant_id, occurred_at, dedupe_key, "
                "   amount_minor, currency, payload) "
                "VALUES (:id, :topic, :tid, :occurred, :dedupe, :amt, :cur, cast(:p as jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "topic": topic,
                "tid": uuid.uuid4(),
                "occurred": occurred_at,
                "dedupe": f"{topic}:{uuid.uuid4().hex}",
                "amt": amount_minor,
                "cur": currency,
                "p": json.dumps(payload),
            },
        )


async def _insert_usage_event(
    sf: async_sessionmaker,
    *,
    topic: str,
    occurred_at: datetime,
    tenant_id: uuid.UUID | None = None,
    correlation_id: str | None = None,
    person_id: uuid.UUID | None = None,
) -> None:
    payload = {"person_id": str(person_id)} if person_id is not None else {}
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO warehouse.fact_usage_event "
                "  (id, event_topic, tenant_id, correlation_id, occurred_at, dedupe_key, payload) "
                "VALUES (:id, :topic, :tid, :corr, :occurred, :dedupe, cast(:p as jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "topic": topic,
                "tid": tenant_id or uuid.uuid4(),
                "corr": correlation_id or f"corr-{uuid.uuid4().hex[:8]}",
                "occurred": occurred_at,
                "dedupe": f"{topic}:{uuid.uuid4().hex}",
                "p": json.dumps(payload),
            },
        )


class TestRevenueAnalytics:
    async def test_sums_invoice_amounts_by_currency(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        await _insert_revenue_event(
            session_factory,
            topic="billing.invoice.paid",
            occurred_at=mid,
            amount_minor=5000,
            currency="USD",
        )
        await _insert_revenue_event(
            session_factory,
            topic="billing.invoice.paid",
            occurred_at=mid,
            amount_minor=3000,
            currency="USD",
        )
        # Outside the window -- must not be counted.
        await _insert_revenue_event(
            session_factory,
            topic="billing.invoice.paid",
            occurred_at=start - timedelta(days=1),
            amount_minor=999_999,
            currency="USD",
        )
        result = await self._run(session_factory, start, end)
        assert result.revenue_minor_by_currency == {"USD": 8000}
        assert result.invoice_count == 2

    async def test_counts_subscription_lifecycle_actions(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        await _insert_revenue_event(
            session_factory, topic="billing.subscription.changed", occurred_at=mid, action="created"
        )
        await _insert_revenue_event(
            session_factory, topic="billing.subscription.changed", occurred_at=mid, action="created"
        )
        await _insert_revenue_event(
            session_factory,
            topic="billing.subscription.changed",
            occurred_at=mid,
            action="canceled",
        )
        await _insert_revenue_event(
            session_factory,
            topic="billing.subscription.changed",
            occurred_at=mid,
            action="upgraded",
        )
        result = await self._run(session_factory, start, end)
        assert result.new_subscriptions == 2
        assert result.cancellations == 1
        assert result.upgrades == 1
        assert result.downgrades == 0

    async def test_churn_rate_uses_active_at_start_of_period(
        self, session_factory: async_sessionmaker
    ) -> None:
        # Same "cumulative before" reasoning as the no-active-subscriptions
        # test below: a random 2030+ window isn't safe here, since another
        # test's "created" event could randomly land before this one's start
        # and inflate active_at_start. Anchor before every other test's data.
        start = datetime(2015, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=1)
        mid = start + timedelta(minutes=30)
        before_period = start - timedelta(days=1)
        # 2 subscriptions created before the period -> active_at_start == 2.
        await _insert_revenue_event(
            session_factory,
            topic="billing.subscription.changed",
            occurred_at=before_period,
            action="created",
        )
        await _insert_revenue_event(
            session_factory,
            topic="billing.subscription.changed",
            occurred_at=before_period,
            action="created",
        )
        # 1 cancels DURING the period.
        await _insert_revenue_event(
            session_factory,
            topic="billing.subscription.changed",
            occurred_at=mid,
            action="canceled",
        )
        result = await self._run(session_factory, start, end)
        assert result.churn_rate == pytest.approx(0.5)

    async def test_churn_rate_is_none_with_no_active_subscriptions(
        self, session_factory: async_sessionmaker
    ) -> None:
        # "Active at start" is cumulative over ALL history before the period,
        # by design (that's what churn needs) -- so this window must start
        # earlier than EVERY other test's data (including the fixed-2015
        # anchor above), or that test's "created" events would be seen as
        # pre-period history here too.
        start = datetime(2005, 1, 1, tzinfo=UTC)
        end = start + timedelta(hours=1)
        result = await self._run(session_factory, start, end)
        assert result.churn_rate is None

    @staticmethod
    async def _run(
        sf: async_sessionmaker, start: datetime, end: datetime
    ) -> analytics.RevenueAnalytics:
        async with admin_session(sf) as s:
            return await analytics.revenue_analytics(s, period_start=start, period_end=end)


class TestUsageAnalytics:
    async def test_analyses_started_and_completed_are_distinct_correlations(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        corr_a, corr_b = f"corr-{uuid.uuid4().hex}", f"corr-{uuid.uuid4().hex}"
        await _insert_usage_event(
            session_factory, topic="video.normalized", occurred_at=mid, correlation_id=corr_a
        )
        await _insert_usage_event(
            session_factory, topic="video.normalized", occurred_at=mid, correlation_id=corr_b
        )
        await _insert_usage_event(
            session_factory, topic="report.ready", occurred_at=mid, correlation_id=corr_a
        )
        async with admin_session(session_factory) as s:
            result = await analytics.usage_analytics(s, period_start=start, period_end=end)
        assert result.analyses_started == 2
        assert result.analyses_completed == 1

    async def test_active_tenants_counts_distinct_tenants(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
        await _insert_usage_event(
            session_factory, topic="shot.classified", occurred_at=mid, tenant_id=tenant_a
        )
        await _insert_usage_event(
            session_factory, topic="dna.updated", occurred_at=mid, tenant_id=tenant_a
        )
        await _insert_usage_event(
            session_factory, topic="shot.classified", occurred_at=mid, tenant_id=tenant_b
        )
        async with admin_session(session_factory) as s:
            result = await analytics.usage_analytics(s, period_start=start, period_end=end)
        assert result.active_tenants == 2

    async def test_active_players_extracted_from_video_normalized_payload(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        person = uuid.uuid4()
        await _insert_usage_event(
            session_factory, topic="video.normalized", occurred_at=mid, person_id=person
        )
        # Same person, second clip -- must not double count.
        await _insert_usage_event(
            session_factory, topic="video.normalized", occurred_at=mid, person_id=person
        )
        async with admin_session(session_factory) as s:
            result = await analytics.usage_analytics(s, period_start=start, period_end=end)
        assert result.active_players == 1

    async def test_events_by_topic_breaks_down_the_period(
        self, session_factory: async_sessionmaker
    ) -> None:
        start, end, mid = _window()
        await _insert_usage_event(session_factory, topic="bat.tracked", occurred_at=mid)
        await _insert_usage_event(session_factory, topic="bat.tracked", occurred_at=mid)
        await _insert_usage_event(session_factory, topic="ball.events", occurred_at=mid)
        async with admin_session(session_factory) as s:
            result = await analytics.usage_analytics(s, period_start=start, period_end=end)
        assert result.events_by_topic["bat.tracked"] == 2
        assert result.events_by_topic["ball.events"] == 1
