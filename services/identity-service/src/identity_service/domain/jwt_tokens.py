"""JWT issuance for identity-service.

Uses ``cip_core.auth`` on the VERIFICATION side (every service shares one
implementation); this module owns ISSUANCE. Access tokens are short-lived
(15 min); refresh tokens are longer-lived (30 days) and revocable via the
``tokens`` table registry.

The refresh-token value handed to the client is NOT the JWT payload — we
issue the JWT as usual but ALSO write its ``jti`` into the ``tokens``
table so /v1/auth/logout can flip ``revoked = true`` and every future
verify catches it via a lookup.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from cip_core.auth import (
    ACCESS_TOKEN_TYPE,
    DEFAULT_ALGORITHM,
    DEFAULT_SIGNING_SECRET_NAME,
    REFRESH_TOKEN_TYPE,
)
from cip_core.settings import get_settings

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """Both tokens returned by /v1/auth/login and /v1/auth/refresh."""

    access_token: str
    refresh_token: str
    refresh_jti: uuid.UUID  # so the caller can persist for revocation
    token_type: str = "Bearer"
    access_expires_in: int = int(ACCESS_TTL.total_seconds())


def _signing_key() -> str:
    provider = get_settings().build_secret_provider()
    return provider.get(DEFAULT_SIGNING_SECRET_NAME)


def _encode(claims: dict[str, Any]) -> str:
    return jwt.encode(claims, _signing_key(), algorithm=DEFAULT_ALGORITHM)


def issue_tokens(
    *,
    person_id: uuid.UUID,
    roles: list[str],
    now: datetime | None = None,
) -> IssuedTokens:
    """Issue a fresh (access, refresh) JWT pair for ``person_id``."""
    now_utc = now or datetime.now(UTC)
    access_jti = uuid.uuid4()
    refresh_jti = uuid.uuid4()

    common: dict[str, Any] = {
        "sub": str(person_id),
        "iat": int(now_utc.timestamp()),
        "iss": "cip-identity",
    }
    access_claims = {
        **common,
        "type": ACCESS_TOKEN_TYPE,
        "roles": roles,
        "exp": int((now_utc + ACCESS_TTL).timestamp()),
        "jti": str(access_jti),
    }
    refresh_claims = {
        **common,
        "type": REFRESH_TOKEN_TYPE,
        "exp": int((now_utc + REFRESH_TTL).timestamp()),
        "jti": str(refresh_jti),
    }

    return IssuedTokens(
        access_token=_encode(access_claims),
        refresh_token=_encode(refresh_claims),
        refresh_jti=refresh_jti,
    )
