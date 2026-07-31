"""Input source adapters (M18 Step 2, §8).

academy-service composes rosters and dashboards from several upstream
reads. Each is a seam, following the "adapters + fakes, defer real infra"
pattern used throughout this platform: a real implementation is deferred, a
deterministic fake lets the pipeline be built and tested now — even for M02,
which physically exists in this repo, since no service in this build has
ever made a real cross-service HTTP call (consistency over convenience).

- :class:`RosterSource` — M02's tenant memberships (who is a player in this
  academy), the roster's ground truth.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class RosterMember:
    """One M02 tenant membership relevant to the roster."""

    person_id: uuid.UUID
    role: str
    display_name: str | None = None


class RosterSource(Protocol):
    async def load(self, tenant_id: uuid.UUID) -> list[RosterMember]:
        """Every current member of this tenant (players and staff), or []."""
        ...


class FakeRosterSource:
    """In-process roster source holding fixtures for dev + tests."""

    def __init__(self) -> None:
        self.members: dict[uuid.UUID, list[RosterMember]] = {}

    def set_members(self, tenant_id: uuid.UUID, members: list[RosterMember]) -> None:
        self.members[tenant_id] = members

    async def load(self, tenant_id: uuid.UUID) -> list[RosterMember]:
        return self.members.get(tenant_id, [])
