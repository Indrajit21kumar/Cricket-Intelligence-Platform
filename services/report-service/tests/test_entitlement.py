"""AI Coach entitlement + usage-metering adapter (M14 Step 7, FR-M14-10)."""

from __future__ import annotations

import asyncio
import uuid

from report_service.domain.entitlement import FakeEntitlementClient

_TENANT = uuid.uuid4()


class TestFakeEntitlementClient:
    def test_allowed_by_default(self) -> None:
        client = FakeEntitlementClient()
        decision = asyncio.run(client.check_ai_coach_entitlement(tenant_id=_TENANT))
        assert decision.allowed is True
        assert decision.reason is None

    def test_denied_when_not_entitled(self) -> None:
        client = FakeEntitlementClient(allowed=False)
        decision = asyncio.run(client.check_ai_coach_entitlement(tenant_id=_TENANT))
        assert decision.allowed is False
        assert decision.reason == "ai_coach_not_entitled"
        assert decision.remaining == 0

    def test_usage_is_recorded_once(self) -> None:
        client = FakeEntitlementClient()
        first = asyncio.run(client.record_ai_coach_usage(tenant_id=_TENANT, idempotency_key="k1"))
        assert first is True

    def test_duplicate_idempotency_key_is_not_double_recorded(self) -> None:
        client = FakeEntitlementClient()
        asyncio.run(client.record_ai_coach_usage(tenant_id=_TENANT, idempotency_key="k1"))
        second = asyncio.run(client.record_ai_coach_usage(tenant_id=_TENANT, idempotency_key="k1"))
        assert second is False

    def test_distinct_keys_are_both_recorded(self) -> None:
        client = FakeEntitlementClient()
        first = asyncio.run(client.record_ai_coach_usage(tenant_id=_TENANT, idempotency_key="k1"))
        second = asyncio.run(client.record_ai_coach_usage(tenant_id=_TENANT, idempotency_key="k2"))
        assert first is True
        assert second is True
