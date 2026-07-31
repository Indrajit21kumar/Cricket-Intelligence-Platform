"""Cross-service seam onto M10's out-of-range flag (M20 Step 6, FR-M20-06).

The out-of-range/reviewed_by_human flag M10 Step 6 computes lives in
biomechanics-service's own TENANT-SCOPED (RLS) ``biomechanics_reports``
table — inaccessible to M20 without a real cross-tenant admin API
biomechanics-service doesn't expose today. Same "adapters + fakes, defer
real infra" pattern this build has used for every cross-service dependency
since M18 (e.g. academy-service's ``RosterSource``) — including in
PRODUCTION ``Deps``, not just tests, since no service in this build has
ever wired a real cross-service HTTP call. :class:`BiomechanicsReviewSource`
is the seam a real sync worker will implement later; :class:`FakeBiomechanicsReviewSource`
backs both tests and (for now) the running service.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PendingReview:
    tenant_id: uuid.UUID
    stroke_ref: str
    #: Comma-joined flagged metric ids, mirroring biomechanics_reports'
    #: own out_of_expected_range flag context (M10 Step 6).
    reason: str


class BiomechanicsReviewSource(Protocol):
    """What M20 needs from biomechanics-service's review flag."""

    async def list_pending(self) -> list[PendingReview]:
        """Every out_of_expected_range report not yet reviewed_by_human, across all tenants."""
        ...

    async def mark_reviewed(self, *, tenant_id: uuid.UUID, stroke_ref: str) -> None:
        """Flip reviewed_by_human -> true for one report once M20 resolves it."""
        ...


class FakeBiomechanicsReviewSource:
    """In-memory stand-in — the only implementation this build has, in
    tests and in the running service alike (see module docstring)."""

    def __init__(self, pending: list[PendingReview] | None = None) -> None:
        self._pending = list(pending or [])
        #: (tenant_id, stroke_ref) pairs the service asked to mark reviewed.
        self.reviewed: list[tuple[uuid.UUID, str]] = []

    async def list_pending(self) -> list[PendingReview]:
        return list(self._pending)

    async def mark_reviewed(self, *, tenant_id: uuid.UUID, stroke_ref: str) -> None:
        self.reviewed.append((tenant_id, stroke_ref))
        self._pending = [
            p
            for p in self._pending
            if not (p.tenant_id == tenant_id and p.stroke_ref == stroke_ref)
        ]

    def add_pending(self, review: PendingReview) -> None:
        """Test/demo helper — seed a flagged report the fake hasn't reported yet."""
        self._pending.append(review)
