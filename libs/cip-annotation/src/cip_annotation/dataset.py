"""Versioned dataset manifests (shared by M07 and M08).

Freezing is what makes a model reproducible: ``bat_runs.dataset_version`` or
``ball_runs.dataset_version`` plus this checksum answers "exactly which frames
did this model learn from?" — the traceability the ENG-007 validation gates
depend on.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from cip_data import admin_session, tenant_session


def dataset_checksum(items: list[tuple[str, str, int]]) -> str:
    """Stable hash over (correlation_id, modality, frame_index), order-independent."""
    joined = "|".join(f"{corr}:{modality}:{index}" for corr, modality, index in sorted(items))
    return hashlib.sha256(joined.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    version: str
    item_count: int
    checksum: str


async def freeze_dataset(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    version: str,
    tenant_ids: Sequence[uuid.UUID],
    modality: str | None = None,
    notes: str | None = None,
) -> DatasetVersion:
    """Freeze the unassigned queued frames of the given tenants into a corpus.

    ``tenant_ids`` is explicit rather than implied, for a structural reason. The
    queue is tenant-scoped under RLS and ``admin_session`` deliberately sees
    NOTHING through that policy, so there is no ambient "every row" view to
    freeze from — and there should not be. A training corpus aggregates many
    academies' players, so the tenants it draws from are named by the operator
    and visible at the call site, rather than a cross-tenant sweep happening
    quietly.

    ``modality`` cuts a bat-only or ball-only corpus; omitted, it freezes both.
    """
    items: list[tuple[str, str, int]] = []
    # Two fully literal statement pairs rather than one interpolated template:
    # nothing is built from a variable, so there is no injection surface to
    # reason about and no suppression comment to trust.
    params: dict[str, object] = {"v": version}
    if modality:
        params["mod"] = modality
        select_sql = (
            "SELECT correlation_id, modality, frame_index FROM annotation_queue "
            "WHERE dataset_version IS NULL AND modality = :mod "
            "ORDER BY correlation_id, modality, frame_index"
        )
        update_sql = (
            "UPDATE annotation_queue SET dataset_version = :v "
            "WHERE dataset_version IS NULL AND modality = :mod"
        )
    else:
        select_sql = (
            "SELECT correlation_id, modality, frame_index FROM annotation_queue "
            "WHERE dataset_version IS NULL "
            "ORDER BY correlation_id, modality, frame_index"
        )
        update_sql = (
            "UPDATE annotation_queue SET dataset_version = :v WHERE dataset_version IS NULL"
        )

    for tenant_id in tenant_ids:
        async with tenant_session(session_factory, tenant_id=tenant_id) as session:
            rows = (await session.execute(text(select_sql), params)).all()
            items.extend((str(r[0]), str(r[1]), int(r[2])) for r in rows)
            await session.execute(text(update_sql), params)

    checksum = dataset_checksum(items)
    async with admin_session(session_factory) as session:
        await session.execute(
            text(
                "INSERT INTO annotation_datasets (id, version, item_count, checksum, notes) "
                "VALUES (:id, :v, :n, :c, :notes)"
            ),
            {
                "id": uuid.uuid4(),
                "v": version,
                "n": len(items),
                "c": checksum,
                "notes": notes,
            },
        )
    return DatasetVersion(version=version, item_count=len(items), checksum=checksum)


async def get_dataset(session: AsyncSession, version: str) -> DatasetVersion | None:
    row = (
        await session.execute(
            text(
                "SELECT version, item_count, checksum FROM annotation_datasets WHERE version = :v"
            ),
            {"v": version},
        )
    ).first()
    if row is None:
        return None
    return DatasetVersion(version=row[0], item_count=int(row[1]), checksum=row[2])
