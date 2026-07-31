"""Integration tests for model oversight (M20 Step 5, FR-M20-05).

Every test uses its own disjoint (since, until) window and its own random
model name -- these functions read/write a single shared, un-tenant-scoped
table, same isolation concern Step 4's analytics tests hit.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from admin_service.domain import model_metrics_repo
from sqlalchemy.ext.asyncio import async_sessionmaker

from cip_data.engine import admin_session

pytestmark = pytest.mark.integration


def _window(hours: int = 2) -> tuple[datetime, datetime]:
    start = datetime(2030, 1, 1, tzinfo=UTC) + timedelta(seconds=random.randint(0, 500_000_000))
    return start, start + timedelta(hours=hours)


class TestRecordAndReadModelMetric:
    async def test_records_and_reads_back_a_single_accuracy_sample(
        self, session_factory: async_sessionmaker
    ) -> None:
        model_name = f"test-model-{uuid.uuid4().hex[:8]}"
        start, until = _window()
        computed_at = start + timedelta(minutes=30)
        async with admin_session(session_factory) as s:
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
                value=0.91,
                computed_at=computed_at,
            )
        async with admin_session(session_factory) as s:
            health = await model_metrics_repo.model_health(
                s, model_name=model_name, since=start, until=until
            )
        assert health.sample_count == 1
        assert health.latest_accuracy == pytest.approx(0.91)
        assert health.latest_accuracy_at == computed_at
        assert health.drift is None  # only 1 point -- drift needs 2

    async def test_drift_is_the_change_across_the_window(
        self, session_factory: async_sessionmaker
    ) -> None:
        model_name = f"test-model-{uuid.uuid4().hex[:8]}"
        start, until = _window()
        async with admin_session(session_factory) as s:
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
                value=0.95,
                computed_at=start + timedelta(minutes=10),
            )
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
                value=0.88,
                computed_at=start + timedelta(minutes=90),
            )
        async with admin_session(session_factory) as s:
            health = await model_metrics_repo.model_health(
                s, model_name=model_name, since=start, until=until
            )
        assert health.sample_count == 2
        assert health.latest_accuracy == pytest.approx(0.88)
        assert health.drift == pytest.approx(0.88 - 0.95)

    async def test_confidence_mean_is_tracked_independently_of_accuracy(
        self, session_factory: async_sessionmaker
    ) -> None:
        model_name = f"test-model-{uuid.uuid4().hex[:8]}"
        start, until = _window()
        computed_at = start + timedelta(minutes=15)
        async with admin_session(session_factory) as s:
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.CONFIDENCE_MEAN,
                value=0.73,
                computed_at=computed_at,
            )
        async with admin_session(session_factory) as s:
            health = await model_metrics_repo.model_health(
                s, model_name=model_name, since=start, until=until
            )
        assert health.confidence_mean == pytest.approx(0.73)
        assert health.confidence_mean_at == computed_at
        # No accuracy samples recorded -- honestly None, not fabricated.
        assert health.latest_accuracy is None
        assert health.sample_count == 0

    async def test_no_data_reports_honestly_empty_not_fabricated(
        self, session_factory: async_sessionmaker
    ) -> None:
        model_name = f"test-model-{uuid.uuid4().hex[:8]}"
        start, until = _window()
        async with admin_session(session_factory) as s:
            health = await model_metrics_repo.model_health(
                s, model_name=model_name, since=start, until=until
            )
        assert health.sample_count == 0
        assert health.latest_accuracy is None
        assert health.drift is None
        assert health.confidence_mean is None
        assert health.accuracy_trend == []

    async def test_samples_outside_the_window_are_excluded(
        self, session_factory: async_sessionmaker
    ) -> None:
        model_name = f"test-model-{uuid.uuid4().hex[:8]}"
        start, until = _window()
        async with admin_session(session_factory) as s:
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
                value=0.5,
                computed_at=start - timedelta(days=1),
            )
            await model_metrics_repo.record_model_metric(
                s,
                model_name=model_name,
                model_version="fake-v1",
                metric_name=model_metrics_repo.ACCURACY_VS_GOLDEN,
                value=0.5,
                computed_at=until + timedelta(days=1),
            )
        async with admin_session(session_factory) as s:
            health = await model_metrics_repo.model_health(
                s, model_name=model_name, since=start, until=until
            )
        assert health.sample_count == 0


def test_known_models_covers_the_golden_dataset_gated_services() -> None:
    assert set(model_metrics_repo.KNOWN_MODELS) == {"pose", "bat", "ball", "shot"}
