"""The consent gate on the annotation queue (M07 Step 2, AC-M07-07).

The rule under test: a frame may only become training data if that player
consented to training use, and a MINOR's consent only counts when a verified
guardian granted it. Everything here is default-deny — the absence of a
consent row is a refusal, not an oversight.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from bat_service.domain.annotation import (
    REASON_SAMPLED,
    SelectedFrame,
    enqueue_frames,
    freeze_dataset,
    get_dataset,
    purge_person,
    queue_size,
)
from cip_core import CONSENT_PROCESSING, CONSENT_TRAINING
from cip_data.engine import admin_session, build_engine, build_session_factory, tenant_session

pytestmark = pytest.mark.integration


@pytest.fixture
def session_factory(_migrated_database: str) -> async_sessionmaker:
    return build_session_factory(build_engine(_migrated_database))


async def _person(sf: async_sessionmaker, *, dob_band: str = "adult") -> uuid.UUID:
    pid = uuid.uuid4()
    async with admin_session(sf) as s:
        await s.execute(
            text("INSERT INTO persons (id, email, dob_band) VALUES (:id, :e, :d)"),
            {"id": pid, "e": f"{pid}@example.test", "d": dob_band},
        )
    return pid


async def _consent(
    sf: async_sessionmaker,
    *,
    person_id: uuid.UUID,
    granted_by: uuid.UUID | None = None,
    consent_type: str = CONSENT_TRAINING,
    tenant_id: uuid.UUID | None = None,
) -> None:
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO consents (id, person_id, tenant_id, type, granted_by, scope) "
                "VALUES (:id, :pid, :tid, :ct, :gb, cast('{}' as jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "pid": person_id,
                "tid": tenant_id,
                "ct": consent_type,
                "gb": granted_by or person_id,
            },
        )


async def _guardianship(
    sf: async_sessionmaker, *, minor: uuid.UUID, guardian: uuid.UUID, verified: bool
) -> None:
    async with admin_session(sf) as s:
        await s.execute(
            text(
                "INSERT INTO guardianships (id, minor_person_id, guardian_person_id, verified) "
                "VALUES (:id, :m, :g, :v)"
            ),
            {"id": uuid.uuid4(), "m": minor, "g": guardian, "v": verified},
        )


def _frames(n: int = 3) -> tuple[SelectedFrame, ...]:
    return tuple(
        SelectedFrame(frame_index=i, reason=REASON_SAMPLED, weak_label={"parts": []})
        for i in range(n)
    )


class TestConsentGate:
    async def test_consented_adult_frames_are_queued(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=person_id,
                frames=_frames(),
            )
        assert result.allowed is True
        assert result.queued == 3
        assert result.consent_reason == "training_consent"

    async def test_no_consent_queues_nothing(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """Default deny: a player who never opted in is not a data source."""
        person_id = await _person(session_factory)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=person_id,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.queued == 0
        assert result.consent_reason == "no_training_consent"

    async def test_processing_consent_alone_is_not_training_consent(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """Agreeing to be analysed is not agreeing to become a training corpus."""
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id, consent_type=CONSENT_PROCESSING)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=person_id,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.consent_reason == "no_training_consent"

    async def test_unidentified_player_is_refused(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=None,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.consent_reason == "unknown_person"


class TestMinors:
    async def test_minor_self_consent_is_refused(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """A child cannot sign their own frames into a training set."""
        minor = await _person(session_factory, dob_band="minor")
        await _consent(session_factory, person_id=minor, granted_by=minor)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=minor,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.consent_reason == "minor_requires_guardian_consent"
        assert result.queued == 0

    async def test_unverified_guardian_consent_is_refused(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        minor = await _person(session_factory, dob_band="minor")
        guardian = await _person(session_factory)
        await _guardianship(session_factory, minor=minor, guardian=guardian, verified=False)
        await _consent(session_factory, person_id=minor, granted_by=guardian)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=minor,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.consent_reason == "minor_requires_guardian_consent"

    async def test_verified_guardian_consent_admits_the_minor(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        minor = await _person(session_factory, dob_band="minor")
        guardian = await _person(session_factory)
        await _guardianship(session_factory, minor=minor, guardian=guardian, verified=True)
        await _consent(session_factory, person_id=minor, granted_by=guardian)

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=minor,
                frames=_frames(2),
            )
        assert result.allowed is True
        assert result.queued == 2
        # The row records WHY it was admitted, for later audit.
        assert result.consent_reason == "guardian_consent"


class TestQueueMechanics:
    async def test_reprocessing_a_clip_does_not_duplicate_frames(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id)
        correlation_id = f"c-{uuid.uuid4().hex[:8]}"

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            first = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                person_id=person_id,
                frames=_frames(),
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            second = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                person_id=person_id,
                frames=_frames(),
            )
            total = await queue_size(s, correlation_id=correlation_id)
        assert first.queued == 3
        assert second.queued == 0  # all conflicts, nothing new
        assert total == 3

    async def test_withdrawal_purges_queued_frames(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """Consent that cannot be revoked is not consent."""
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id)
        correlation_id = f"c-{uuid.uuid4().hex[:8]}"

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                person_id=person_id,
                frames=_frames(),
            )
        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            removed = await purge_person(s, person_id=person_id)
        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            remaining = await queue_size(s, correlation_id=correlation_id)
        assert removed == 3
        assert remaining == 0

    async def test_withdrawn_consent_blocks_further_frames(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id)
        async with admin_session(session_factory) as s:
            await s.execute(
                text(
                    "UPDATE consents SET withdrawn_at = now() WHERE person_id = :pid AND type = :ct"
                ),
                {"pid": person_id, "ct": CONSENT_TRAINING},
            )

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            result = await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=f"c-{uuid.uuid4().hex[:8]}",
                person_id=person_id,
                frames=_frames(),
            )
        assert result.allowed is False
        assert result.consent_reason == "no_training_consent"


class TestDatasetFreeze:
    async def test_freeze_versions_and_checksums_the_queue(
        self, session_factory: async_sessionmaker, tenant_id: uuid.UUID
    ) -> None:
        """A detector must be traceable to exactly the frames it learned from."""
        person_id = await _person(session_factory)
        await _consent(session_factory, person_id=person_id)
        correlation_id = f"c-{uuid.uuid4().hex[:8]}"
        version = f"bat-ds-{uuid.uuid4().hex[:8]}"

        async with tenant_session(session_factory, tenant_id=tenant_id) as s:
            await enqueue_frames(
                s,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                person_id=person_id,
                frames=_frames(4),
            )
        frozen = await freeze_dataset(
            session_factory, version=version, tenant_ids=[tenant_id], notes="test cut"
        )
        async with admin_session(session_factory) as s:
            stored = await get_dataset(s, version)

        assert frozen.item_count == 4
        assert stored is not None
        assert stored.checksum == frozen.checksum

        # Frozen rows are stamped, so a later freeze does not re-include them.
        async with admin_session(session_factory) as s:
            unassigned = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM annotation_queue "
                        "WHERE correlation_id = :c AND dataset_version IS NULL"
                    ),
                    {"c": correlation_id},
                )
            ).scalar_one()
        assert unassigned == 0
