"""Integration tests for the success-metric board (M20 Step 7, §13 KPIs).

Retention and accuracy read GLOBAL, un-tenant-scoped tables, so (as in
Step 4/5) each test uses its own disjoint time window; ``total_academies``/
``countries`` read the real ``tenants`` table directly and only assert
"at least" the tenants this test itself created, since other tests/sessions
have their own real tenant rows too.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from admin_service.domain import success_metrics_repo
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


def _window() -> tuple[datetime, datetime, datetime]:
    """A random, disjoint-from-everything-else (previous_start, start, end) triple."""
    previous_start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(
        seconds=random.randint(0, 500_000_000)
    )
    start = previous_start + timedelta(days=30)
    end = start + timedelta(days=30)
    return previous_start, start, end


async def _make_tenant(sf: async_sessionmaker, prefix: str, *, region: str = "IN") -> uuid.UUID:
    tid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO tenants (id, name, type, region) VALUES (:id, :n, 'academy', :region)"
            ),
            {"id": tid, "n": f"{prefix}-{uuid.uuid4().hex[:8]}", "region": region},
        )
    return tid


async def _insert_usage_event(
    sf: async_sessionmaker, *, tenant_id: uuid.UUID, occurred_at: datetime
) -> None:
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO warehouse.fact_usage_event "
                "  (id, event_topic, tenant_id, correlation_id, occurred_at, dedupe_key) "
                "VALUES (:id, 'shot.classified', :tid, :corr, :occurred, :dedupe)"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "corr": f"corr-{uuid.uuid4().hex[:8]}",
                "occurred": occurred_at,
                "dedupe": f"retention-{uuid.uuid4().hex}",
            },
        )


class TestAcademyAndCountryCounts:
    async def test_counts_include_a_freshly_created_academy(
        self, session_factory: async_sessionmaker
    ) -> None:
        await _make_tenant(session_factory, "success-metrics", region="US")
        _prev_start, start, end = _window()
        async with admin_session(session_factory) as s:
            metrics = await success_metrics_repo.compute_success_metrics(
                s, previous_period_start=start, period_start=start, period_end=end
            )
        assert metrics.total_academies >= 1
        assert metrics.countries >= 1


class TestRetention:
    async def test_tenant_active_in_both_periods_is_retained(
        self, session_factory: async_sessionmaker
    ) -> None:
        previous_start, start, end = _window()
        tenant_id = uuid.uuid4()
        await _insert_usage_event(
            session_factory, tenant_id=tenant_id, occurred_at=previous_start + timedelta(days=1)
        )
        await _insert_usage_event(
            session_factory, tenant_id=tenant_id, occurred_at=start + timedelta(days=1)
        )
        async with admin_session(session_factory) as s:
            metrics = await success_metrics_repo.compute_success_metrics(
                s, previous_period_start=previous_start, period_start=start, period_end=end
            )
        assert metrics.active_tenants_previous_period == 1
        assert metrics.retained_tenants == 1
        assert metrics.retention_rate == pytest.approx(1.0)

    async def test_tenant_active_only_previously_is_not_retained(
        self, session_factory: async_sessionmaker
    ) -> None:
        previous_start, start, end = _window()
        tenant_id = uuid.uuid4()
        await _insert_usage_event(
            session_factory, tenant_id=tenant_id, occurred_at=previous_start + timedelta(days=1)
        )
        async with admin_session(session_factory) as s:
            metrics = await success_metrics_repo.compute_success_metrics(
                s, previous_period_start=previous_start, period_start=start, period_end=end
            )
        assert metrics.active_tenants_previous_period == 1
        assert metrics.retained_tenants == 0
        assert metrics.retention_rate == pytest.approx(0.0)

    async def test_retention_rate_is_none_with_no_previous_activity(
        self, session_factory: async_sessionmaker
    ) -> None:
        previous_start, start, end = _window()
        async with admin_session(session_factory) as s:
            metrics = await success_metrics_repo.compute_success_metrics(
                s, previous_period_start=previous_start, period_start=start, period_end=end
            )
        assert metrics.active_tenants_previous_period == 0
        assert metrics.retention_rate is None


class TestModelAccuracy:
    async def test_no_data_reports_none_not_fabricated(
        self, session_factory: async_sessionmaker
    ) -> None:
        previous_start, start, end = _window()
        async with admin_session(session_factory) as s:
            metrics = await success_metrics_repo.compute_success_metrics(
                s, previous_period_start=previous_start, period_start=start, period_end=end
            )
        # This window is freshly random-picked, so no model metric exists in it.
        assert metrics.models_with_accuracy_data == 0
        assert metrics.average_model_accuracy is None
