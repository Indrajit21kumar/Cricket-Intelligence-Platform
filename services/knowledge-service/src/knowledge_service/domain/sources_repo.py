"""sources + rule_sources repository (M12 Step 8, Book 10).

A Source is a cited external authority; a rule links to sources with a relation
(supported_by / contradicted_by). A source must be SAB-vetted (``vetted_by``
set) before it can back a served rule. Global store -> ``admin_session``.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SOURCE_COLUMNS = (
    "id, type, authors, year, title, authority, url_or_ref, license_note, vetted_by, created_at"
)
_LINK_COLUMNS = "id, rule_id, source_id, relation, locator, created_at"


async def insert_source(
    session: AsyncSession,
    *,
    type_: str,
    title: str,
    authors: str | None,
    year: int | None,
    authority: str | None,
    url_or_ref: str | None,
    license_note: str | None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO sources "  # nosec B608 -- constant columns
                    "  (id, type, authors, year, title, authority, url_or_ref, license_note) "
                    "VALUES (:id, :t, :au, :yr, :ti, :auth, :url, :lic) "
                    f"RETURNING {_SOURCE_COLUMNS}"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": type_,
                    "au": authors,
                    "yr": year,
                    "ti": title,
                    "auth": authority,
                    "url": url_or_ref,
                    "lic": license_note,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def get_source(session: AsyncSession, source_id: uuid.UUID) -> dict[str, Any] | None:
    query = f"SELECT {_SOURCE_COLUMNS} FROM sources WHERE id = :id"  # nosec B608
    row = (await session.execute(text(query), {"id": source_id})).mappings().first()
    return dict(row) if row else None


async def vet_source(
    session: AsyncSession, source_id: uuid.UUID, *, vetted_by: dict[str, Any]
) -> dict[str, Any] | None:
    row = (
        (
            await session.execute(
                text(
                    "UPDATE sources SET vetted_by = cast(:vb as jsonb), "  # nosec B608
                    f"updated_at = now() WHERE id = :id RETURNING {_SOURCE_COLUMNS}"
                ),
                {"id": source_id, "vb": json.dumps(vetted_by)},
            )
        )
        .mappings()
        .first()
    )
    return dict(row) if row else None


async def link_source(
    session: AsyncSession,
    *,
    rule_id: str,
    source_id: uuid.UUID,
    relation: str,
    locator: str | None,
) -> dict[str, Any]:
    row = (
        (
            await session.execute(
                text(
                    "INSERT INTO rule_sources (id, rule_id, source_id, relation, locator) "
                    "VALUES (:id, :rid, :sid, :rel, :loc) "
                    "ON CONFLICT (rule_id, source_id, relation) DO UPDATE SET "
                    "  locator = EXCLUDED.locator "
                    f"RETURNING {_LINK_COLUMNS}"  # nosec B608
                ),
                {
                    "id": uuid.uuid4(),
                    "rid": rule_id,
                    "sid": source_id,
                    "rel": relation,
                    "loc": locator,
                },
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def sources_for_rule(session: AsyncSession, rule_id: str) -> list[dict[str, Any]]:
    """Resolved sources linked to a rule: link fields + the source record."""
    query = (
        "SELECT rs.relation, rs.locator, "  # nosec B608 -- no user interpolation
        "  s.id AS source_id, s.type, s.authors, s.year, s.title, s.authority, "
        "  s.url_or_ref, s.vetted_by "
        "FROM rule_sources rs JOIN sources s ON s.id = rs.source_id "
        "WHERE rs.rule_id = :rid ORDER BY rs.created_at"
    )
    rows = (await session.execute(text(query), {"rid": rule_id})).mappings().all()
    return [dict(r) for r in rows]
