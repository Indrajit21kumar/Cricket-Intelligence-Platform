"""M03 entitlement + usage client adapter (M05 Step 2/7).

M05 is the first stage that consumes a billable analysis unit, so it checks
the analysis quota with M03 *before* admitting a clip (FR-M05-02) and records
one ``analysis.consumed`` usage event when a clip is admitted (FR-M05-08).

The :class:`EntitlementClient` protocol is the seam for the real HTTP client
(calls M03 ``POST /v1/entitlements/check`` and ``POST /v1/usage``). Step 2
ships a :class:`FakeEntitlementClient` so the entitlement gate + metering are
testable without standing up M03 — the "adapter + fake" decision again.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol

#: The M03 entitlement key M05 gates on.
ANALYSIS_QUOTA_KEY = "analysis.quota_monthly"
#: The M03 meter M05 draws down.
ANALYSIS_METER_KEY = "analysis.consumed"


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    remaining: int | None
    reason: str | None  # e.g. 'analysis_quota_exhausted' when denied


class EntitlementClient(Protocol):
    """Adapter over M03's entitlement + usage APIs."""

    async def check_analysis_quota(self, *, tenant_id: uuid.UUID) -> EntitlementDecision:
        """Ask M03 whether this tenant may run another analysis."""
        ...

    async def record_analysis_usage(self, *, tenant_id: uuid.UUID, idempotency_key: str) -> bool:
        """Record one ``analysis.consumed`` unit. Returns True if newly recorded
        (False on idempotent replay). Exactly-once per idempotency_key."""
        ...


class FakeEntitlementClient:
    """In-process M03 stand-in for dev + tests.

    ``allowed`` / ``remaining`` are mutable so a test can flip the gate to a
    denial (``deps.entitlement_client.allowed = False``) — the seam the
    over-quota test hangs off. ``recorded`` tracks idempotency keys so metering
    is exactly-once.
    """

    def __init__(self, *, allowed: bool = True, remaining: int = 5) -> None:
        self.allowed = allowed
        self.remaining = remaining
        self.recorded: set[str] = set()

    async def check_analysis_quota(self, *, tenant_id: uuid.UUID) -> EntitlementDecision:
        _ = tenant_id
        if self.allowed:
            return EntitlementDecision(allowed=True, remaining=self.remaining, reason=None)
        return EntitlementDecision(allowed=False, remaining=0, reason="analysis_quota_exhausted")

    async def record_analysis_usage(self, *, tenant_id: uuid.UUID, idempotency_key: str) -> bool:
        _ = tenant_id
        if idempotency_key in self.recorded:
            return False
        self.recorded.add(idempotency_key)
        return True
