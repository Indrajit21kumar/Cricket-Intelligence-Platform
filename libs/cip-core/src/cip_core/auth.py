"""Reusable JWT verification for every CIP service.

The identity-service issues tokens; every other service verifies them via
:func:`require_authenticated`. Keeping the verification logic in cip-core
means every service uses one implementation, one bug surface, and one
audit review — Book 3 §5.1 (RBAC on every endpoint) is enforced from
one place.

Signing key + algorithm come from :class:`Settings`; the actual JWT lib
is PyJWT. HS256 for M02 dev; production rotates to RS256 with the signing
key from cloud KMS (deferred with cip binding).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header

from cip_core.errors import Forbidden, Unauthenticated
from cip_core.settings import get_settings

DEFAULT_ALGORITHM = "HS256"
# nosec B105: these are token-type identifiers, not passwords.
ACCESS_TOKEN_TYPE = "access"  # nosec B105
REFRESH_TOKEN_TYPE = "refresh"  # nosec B105
DEFAULT_SIGNING_SECRET_NAME = "CIP_JWT_SIGNING_KEY"  # nosec B105


@dataclass(frozen=True, slots=True)
class AuthenticatedPrincipal:
    """The verified caller — passed to route handlers via Depends."""

    person_id: uuid.UUID
    #: Roles granted to this principal across their tenants
    #: (list because a person can be coach in academy A + player in academy B).
    roles: tuple[str, ...] = field(default_factory=tuple)
    #: JWT ID (jti) — for revocation checks + audit trail.
    token_id: str = ""
    #: Raw claims dict — for services that need custom claims.
    claims: dict[str, Any] = field(default_factory=dict)


def _signing_key() -> str:
    settings = get_settings()
    provider = settings.build_secret_provider()
    return provider.get(DEFAULT_SIGNING_SECRET_NAME)


def verify_token(token: str, *, token_type: str = ACCESS_TOKEN_TYPE) -> dict[str, Any]:
    """Decode + verify a CIP JWT; raise :class:`Unauthenticated` on failure.

    Enforces the ``token_type`` claim so an access token can't be swapped
    for a refresh token (each has a different privilege scope).
    """
    try:
        claims = jwt.decode(token, _signing_key(), algorithms=[DEFAULT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise Unauthenticated("Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("Token is invalid") from exc

    if claims.get("type") != token_type:
        raise Unauthenticated(f"Expected {token_type} token")
    return claims


def require_authenticated(
    authorization: Annotated[str | None, Header()] = None,
) -> AuthenticatedPrincipal:
    """FastAPI dependency: verify Bearer JWT, return the principal.

    Deny-by-default: any endpoint that uses this dependency rejects
    requests without a valid access token. Use :func:`require_role` on
    top when a specific role is required.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated("Bearer token required")
    token = authorization.split(" ", 1)[1].strip()
    claims = verify_token(token, token_type=ACCESS_TOKEN_TYPE)

    try:
        person_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise Unauthenticated("Malformed subject in token") from exc

    roles_raw = claims.get("roles", [])
    if not isinstance(roles_raw, list):
        raise Unauthenticated("Malformed roles claim")
    roles = tuple(str(r) for r in roles_raw)

    return AuthenticatedPrincipal(
        person_id=person_id,
        roles=roles,
        token_id=str(claims.get("jti", "")),
        claims=claims,
    )


def require_role(
    *allowed_roles: str,
) -> Callable[[AuthenticatedPrincipal], AuthenticatedPrincipal]:
    """FastAPI dependency factory: allow only principals with at least one
    of ``allowed_roles``. 403 with envelope on mismatch."""

    def _dep(
        principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
    ) -> AuthenticatedPrincipal:
        if not set(principal.roles) & set(allowed_roles):
            raise Forbidden(
                "Insufficient role",
                details={"required_any_of": list(allowed_roles)},
            )
        return principal

    return _dep
