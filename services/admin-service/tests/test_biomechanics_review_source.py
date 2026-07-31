"""Unit tests for the Fake biomechanics review source (M20 Step 6)."""

from __future__ import annotations

import uuid

from admin_service.domain.biomechanics_review_source import (
    FakeBiomechanicsReviewSource,
    PendingReview,
)


async def test_list_pending_returns_seeded_items() -> None:
    tenant_id = uuid.uuid4()
    review = PendingReview(tenant_id=tenant_id, stroke_ref="s1", reason="bat_speed")
    source = FakeBiomechanicsReviewSource([review])
    assert await source.list_pending() == [review]


async def test_mark_reviewed_removes_the_item_and_records_it() -> None:
    tenant_id = uuid.uuid4()
    review = PendingReview(tenant_id=tenant_id, stroke_ref="s1", reason="bat_speed")
    source = FakeBiomechanicsReviewSource([review])
    await source.mark_reviewed(tenant_id=tenant_id, stroke_ref="s1")
    assert await source.list_pending() == []
    assert source.reviewed == [(tenant_id, "s1")]


async def test_add_pending_seeds_a_new_flagged_stroke() -> None:
    source = FakeBiomechanicsReviewSource()
    tenant_id = uuid.uuid4()
    source.add_pending(PendingReview(tenant_id=tenant_id, stroke_ref="s2", reason="hip_rotation"))
    pending = await source.list_pending()
    assert len(pending) == 1
    assert pending[0].stroke_ref == "s2"
