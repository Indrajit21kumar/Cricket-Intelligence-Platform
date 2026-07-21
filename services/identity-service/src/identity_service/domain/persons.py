"""Person + credential repository — thin SQLAlchemy wrappers.

Repositories keep raw SQL in one place and give routes small, testable
helpers. Global tables (``persons``, ``credentials``, ``tokens``) don't need
tenant scoping, so callers use :func:`cip_data.admin_session` here.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def create_person(
    session: AsyncSession,
    *,
    email: str,
    dob_band: str | None,
    display_name: str | None = None,
) -> uuid.UUID:
    """Insert a row into ``persons`` in the ``pending_verification`` status.

    Email uniqueness is enforced at the DB level; a duplicate raises
    :class:`sqlalchemy.exc.IntegrityError` which callers turn into a 409.
    """
    person_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO persons (id, email, dob_band, display_name) "
            "VALUES (:id, :email, :dob, :name)"
        ),
        {"id": person_id, "email": email, "dob": dob_band, "name": display_name},
    )
    return person_id


async def get_person_by_email(session: AsyncSession, email: str) -> dict[str, Any] | None:
    """Return the person row (as dict) matching ``email`` or ``None``."""
    result = await session.execute(
        text("SELECT id, email, status, dob_band, display_name FROM persons WHERE email = :email"),
        {"email": email},
    )
    row = result.mappings().first()
    return dict(row) if row else None


async def set_person_status(session: AsyncSession, *, person_id: uuid.UUID, status: str) -> None:
    """Update the ``status`` column on a person."""
    await session.execute(
        text("UPDATE persons SET status = :status, updated_at = now() WHERE id = :id"),
        {"status": status, "id": person_id},
    )


async def create_password_credential(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    password_hash: str,
) -> uuid.UUID:
    """Insert a ``type='password'`` credential row for a person."""
    cred_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO credentials (id, person_id, type, password_hash) "
            "VALUES (:id, :pid, 'password', :hash)"
        ),
        {"id": cred_id, "pid": person_id, "hash": password_hash},
    )
    return cred_id


async def get_password_hash(session: AsyncSession, person_id: uuid.UUID) -> str | None:
    """Return the stored password hash for ``person_id`` (or ``None``)."""
    result = await session.execute(
        text(
            "SELECT password_hash FROM credentials "
            "WHERE person_id = :pid AND type = 'password' "
            "ORDER BY created_at DESC LIMIT 1"
        ),
        {"pid": person_id},
    )
    row = result.first()
    return row[0] if row else None


async def store_token(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
    kind: str,
    token_hash: str,
    expires_at_value: datetime,
) -> uuid.UUID:
    """Insert a ``tokens`` row (verify/reset/refresh)."""
    token_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO tokens (id, person_id, kind, token_hash, expires_at) "
            "VALUES (:id, :pid, :kind, :hash, :exp)"
        ),
        {
            "id": token_id,
            "pid": person_id,
            "kind": kind,
            "hash": token_hash,
            "exp": expires_at_value,
        },
    )
    return token_id


async def claim_token(
    session: AsyncSession,
    *,
    token_hash: str,
    kind: str,
) -> uuid.UUID | None:
    """Return the person_id owning ``token_hash`` if unrevoked + unexpired.

    Marks the token as revoked in the same statement so it cannot be
    replayed. Returns ``None`` if no matching live token exists.
    """
    result = await session.execute(
        text(
            "UPDATE tokens SET revoked = true "
            "WHERE token_hash = :hash "
            "  AND kind = :kind "
            "  AND revoked = false "
            "  AND expires_at > now() "
            "RETURNING person_id"
        ),
        {"hash": token_hash, "kind": kind},
    )
    row = result.first()
    return row[0] if row else None
