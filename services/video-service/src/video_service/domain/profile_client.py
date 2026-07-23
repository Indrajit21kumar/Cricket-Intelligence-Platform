"""M04 player-profile client adapter (M05 Step 5).

Calibration falls back to the player's height (from M04) when stumps aren't
in frame. The :class:`ProfileClient` protocol is the seam for the real HTTP
client (M04 ``GET /v1/players/{personId}/attributes``); Step 5 ships a
:class:`FakeProfileClient` so calibration is testable without M04 running —
the "adapter + fake" decision once more.
"""

from __future__ import annotations

import uuid
from typing import Protocol


class ProfileClient(Protocol):
    """Adapter over M04's attribute read."""

    async def get_player_height_cm(
        self, *, tenant_id: uuid.UUID, person_id: uuid.UUID
    ) -> float | None:
        """Player height in cm, or None if unknown / no consent."""
        ...


class FakeProfileClient:
    """In-process M04 stand-in. ``height_cm`` is mutable so a test can force
    the no-height path (set to None)."""

    def __init__(self, *, height_cm: float | None = 175.0) -> None:
        self.height_cm = height_cm

    async def get_player_height_cm(
        self, *, tenant_id: uuid.UUID, person_id: uuid.UUID
    ) -> float | None:
        _ = (tenant_id, person_id)
        return self.height_cm
