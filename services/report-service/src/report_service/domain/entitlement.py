"""AI Coach entitlement gating + cost metering to M03 (M14 Step 7, FR-M14-10, NFR-M14-04).

AI Coach is a Pro-only feature (Book 3 Ch. 3). Follows the same Protocol +
Fake adapter pattern as every other cross-service billing check in this
build (M05's ``EntitlementClient`` for the video-analysis quota): the real
HTTP call to billing-service is deferred; :class:`FakeEntitlementClient`
lets the gating + metering logic be built and tested now, and a real
implementation swaps in later without touching :mod:`report_service.domain.coach`.

``ai_coach.consumed`` is metered once per question asked while entitled,
regardless of whether the answer or a defer is what came back — mirroring
M05's ``analysis.consumed`` (metered once per completed upload, not per
internal compute step): the billable unit is "an AI Coach interaction",
not raw LLM token cost.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

AI_COACH_FEATURE_KEY = "feature.ai_coach"
AI_COACH_METER_KEY = "ai_coach.consumed"


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    remaining: int | None
    reason: str | None


class EntitlementClient(Protocol):
    async def check_ai_coach_entitlement(self, *, tenant_id: uuid.UUID) -> EntitlementDecision:
        """Whether this tenant's plan includes the AI Coach (feature.ai_coach)."""
        ...

    async def record_ai_coach_usage(self, *, tenant_id: uuid.UUID, idempotency_key: str) -> bool:
        """Meter one AI Coach interaction; True if newly recorded, False if a duplicate."""
        ...


class FakeEntitlementClient:
    """In-process entitlement/metering stand-in for dev + tests."""

    def __init__(self, *, allowed: bool = True, remaining: int | None = None) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.recorded_keys: set[str] = set()

    async def check_ai_coach_entitlement(self, *, tenant_id: uuid.UUID) -> EntitlementDecision:
        if self.allowed:
            return EntitlementDecision(allowed=True, remaining=self.remaining, reason=None)
        return EntitlementDecision(allowed=False, remaining=0, reason="ai_coach_not_entitled")

    async def record_ai_coach_usage(self, *, tenant_id: uuid.UUID, idempotency_key: str) -> bool:
        if idempotency_key in self.recorded_keys:
            return False
        self.recorded_keys.add(idempotency_key)
        return True
