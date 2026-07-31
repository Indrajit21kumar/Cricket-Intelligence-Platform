"""shared_reports repository integration tests (M18 Step 7)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from academy_service.domain import shared_reports_repo
from cip_data.engine import tenant_session

pytestmark = pytest.mark.integration


class TestInsertShare:
    async def test_insert_round_trips(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        shared_by = uuid.uuid4()
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            row = await shared_reports_repo.insert_share(
                session,
                tenant_id=tenant_id,
                report_ref="report-123",
                shared_with=f"guardian:{uuid.uuid4()}",
                shared_by=shared_by,
            )
        assert row["report_ref"] == "report-123"
        assert row["shared_by"] == shared_by

    async def test_list_shares_for_report_orders_most_recent_first(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            first = await shared_reports_repo.insert_share(
                session,
                tenant_id=tenant_id,
                report_ref="report-multi",
                shared_with=f"guardian:{uuid.uuid4()}",
                shared_by=None,
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            second = await shared_reports_repo.insert_share(
                session,
                tenant_id=tenant_id,
                report_ref="report-multi",
                shared_with=f"coach:{uuid.uuid4()}",
                shared_by=None,
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = await shared_reports_repo.list_shares_for_report(
                session, tenant_id=tenant_id, report_ref="report-multi"
            )
        assert {r["id"] for r in rows} == {first["id"], second["id"]}

    async def test_unrelated_report_ref_is_not_returned(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            await shared_reports_repo.insert_share(
                session,
                tenant_id=tenant_id,
                report_ref="report-a",
                shared_with=f"guardian:{uuid.uuid4()}",
                shared_by=None,
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = await shared_reports_repo.list_shares_for_report(
                session, tenant_id=tenant_id, report_ref="report-b"
            )
        assert rows == []
