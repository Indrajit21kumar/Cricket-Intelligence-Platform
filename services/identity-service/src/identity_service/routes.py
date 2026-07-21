"""Auth routes — M02 Steps 2+3.

- Register / verify-email / login / refresh / logout / logout-all
- Login returns real JWTs (access + refresh) as of Step 3
- Later steps add: RBAC (4), memberships + /me (5), consents (6),
  OAuth (7), account lifecycle (8)
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from datetime import date as date_type
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cip_core import (
    REFRESH_TOKEN_TYPE,
    AuthenticatedPrincipal,
    BadRequest,
    Conflict,
    NotFound,
    RateLimited,
    Unauthenticated,
    audit_record,
    require_authenticated,
    require_idempotency_key,
    require_role,
    roles,
)
from cip_core.settings import get_settings
from cip_data import admin_session
from identity_service.deps import Deps, get_deps
from identity_service.domain import lockout
from identity_service.domain.jwt_tokens import (
    REFRESH_TTL,
    IssuedTokens,
    issue_tokens,
)
from identity_service.domain.memberships import list_roles_for_person
from identity_service.domain.password import Hasher
from identity_service.domain.persons import (
    claim_token,
    create_password_credential,
    create_person,
    get_password_hash,
    get_person_by_email,
    set_person_status,
    store_token,
)
from identity_service.domain.verification import (
    expires_at,
    hash_token,
    new_verification_token,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_hasher = Hasher()

MINOR_MAX_AGE = 18


# --- request/response models ----------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(..., min_length=12, max_length=200)
    dob: date_type
    display_name: str | None = Field(None, max_length=200)


class RegisterResponse(BaseModel):
    person_id: uuid.UUID
    status: str
    verification_url_hint: str = Field(
        ...,
        description=(
            "Dev-only. In prod the verification URL goes out via M19 "
            "Notification service; this field is present so integration "
            "tests can pick up the token without scraping logs."
        ),
    )


class VerifyEmailRequest(BaseModel):
    token: str = Field(..., min_length=8, max_length=200)


class VerifyEmailResponse(BaseModel):
    person_id: uuid.UUID
    status: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(..., min_length=1, max_length=200)


class TokenResponse(BaseModel):
    """Wire shape for /v1/auth/login and /v1/auth/refresh (Book 3 §3.1)."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(..., description="Access-token lifetime in seconds")


class RefreshRequest(BaseModel):
    refresh_token: str = Field(..., min_length=8)


# --- helpers ---------------------------------------------------------------


def _dob_band(dob: date_type) -> str:
    today = date_type.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return "adult" if years >= MINOR_MAX_AGE else "minor"


def _to_wire(tokens: IssuedTokens) -> TokenResponse:
    return TokenResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        expires_in=tokens.access_expires_in,
    )


async def _issue_and_persist_refresh(
    session: AsyncSession,
    *,
    person_id: uuid.UUID,
) -> IssuedTokens:
    """Issue an (access, refresh) pair and persist the refresh JTI.

    Looks up the person's current active roles from memberships so the
    JWT's ``roles`` claim reflects live tenant assignments — Step 5's
    contribution to the auth path.
    """
    person_roles = await list_roles_for_person(session, person_id=person_id)
    tokens = issue_tokens(person_id=person_id, roles=person_roles)
    await store_token(
        session,
        person_id=person_id,
        kind="refresh",
        # JTI is not secret; store as-is so revocation can flip by jti.
        token_hash=str(tokens.refresh_jti),
        expires_at_value=datetime.now(UTC) + REFRESH_TTL,
    )
    return tokens


# --- routes ---------------------------------------------------------------


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    body: RegisterRequest,
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    deps: Annotated[Deps, Depends(get_deps)],
) -> RegisterResponse:
    """Create a person + password credential, issue a verification token."""
    dob_band = _dob_band(body.dob)
    password_hash = _hasher.hash(body.password.get_secret_value())

    raw_token = new_verification_token()
    token_hash_value = hash_token(raw_token)

    try:
        async with admin_session(deps.session_factory) as session:
            person_id = await create_person(
                session,
                email=body.email,
                dob_band=dob_band,
                display_name=body.display_name,
            )
            await create_password_credential(
                session, person_id=person_id, password_hash=password_hash
            )
            await store_token(
                session,
                person_id=person_id,
                kind="verify",
                token_hash=token_hash_value,
                expires_at_value=expires_at(),
            )
    except IntegrityError as exc:
        raise Conflict("Email already registered") from exc

    # Log by person_id only — email is PII and MUST NOT be logged (Book 3
    # §5.2, AC-M02-06).
    log.info(
        "identity.verification.token_issued",
        extra={"person_id": str(person_id)},
    )
    return RegisterResponse(
        person_id=person_id,
        status="pending_verification",
        verification_url_hint=raw_token,
    )


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmailRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> VerifyEmailResponse:
    """Consume a verification token; flip the person to ``active``."""
    async with admin_session(deps.session_factory) as session:
        person_id = await claim_token(session, token_hash=hash_token(body.token), kind="verify")
        if person_id is None:
            raise NotFound("Verification token is invalid, expired, or already used")

        row = (
            await session.execute(
                text("SELECT dob_band FROM persons WHERE id = :id"),
                {"id": person_id},
            )
        ).first()
        if row is None:
            raise NotFound("Person no longer exists")
        dob_band = row[0]

        new_status = "pending_consent" if dob_band == "minor" else "active"
        await set_person_status(session, person_id=person_id, status=new_status)

    return VerifyEmailResponse(person_id=person_id, status=new_status)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> TokenResponse:
    """Verify email + password; issue access + refresh JWTs.

    Same-shape 401 for both "unknown email" and "wrong password" — no
    account enumeration. Brute-force protected: too many failures locks the
    account for a window (AC-M02-05), checked before the password.
    """
    invalid = Unauthenticated("Invalid email or password")

    # Brute-force gate (AC-M02-05) — reject locked accounts up front.
    if await lockout.is_locked(deps.redis, body.email):
        raise RateLimited(
            "Too many failed login attempts. Try again later.",
        )

    async def _fail() -> None:
        """Record a failed attempt; raise the generic 401 (or 429 on lock)."""
        locked = await lockout.record_failure(deps.redis, body.email)
        if locked:
            raise RateLimited("Too many failed login attempts. Try again later.")
        raise invalid

    async with admin_session(deps.session_factory) as session:
        person = await get_person_by_email(session, body.email)
        if person is None:
            await _fail()
            raise invalid  # unreachable — _fail() always raises; narrows type
        password_hash = await get_password_hash(session, person["id"])
        if password_hash is None:
            await _fail()
        if not _hasher.verify(password_hash or "", body.password.get_secret_value()):
            await _fail()
        if person["status"] == "pending_verification":
            raise BadRequest("Email is not yet verified")
        if person["status"] == "pending_consent":
            raise BadRequest("Guardian consent required before login")
        if person["status"] != "active":
            raise BadRequest(f"Account status is {person['status']!r}; cannot log in")

        tokens = await _issue_and_persist_refresh(session, person_id=person["id"])
        await audit_record(
            session,
            action="auth.login",
            entity=f"person:{person['id']}",
            actor=f"person:{person['id']}",
        )

    # Successful login clears the failure counter.
    await lockout.clear(deps.redis, body.email)
    return _to_wire(tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    body: RefreshRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> TokenResponse:
    """Exchange a refresh token for a fresh (access, refresh) pair.

    Refresh rotation: the presented refresh is revoked and a new one is
    issued. Prevents refresh-token theft from granting indefinite access.
    """
    # Verify the JWT signature + expiry + type.
    try:
        claims = jwt.decode(
            body.refresh_token,
            get_settings().build_secret_provider().get("CIP_JWT_SIGNING_KEY"),
            algorithms=["HS256"],
        )
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("Invalid or expired refresh token") from exc

    if claims.get("type") != REFRESH_TOKEN_TYPE:
        raise Unauthenticated("Not a refresh token")

    jti = claims.get("jti", "")
    person_id_raw = claims.get("sub", "")

    async with admin_session(deps.session_factory) as session:
        # Atomically revoke the presented refresh JTI. If it was already
        # revoked (rotation replay, logout, or logout-all) claim_token
        # returns None and we reject.
        revoked_person = await claim_token(session, token_hash=jti, kind="refresh")
        if revoked_person is None:
            raise Unauthenticated("Refresh token has been revoked")
        try:
            person_id = uuid.UUID(person_id_raw)
        except ValueError as exc:
            raise Unauthenticated("Malformed subject") from exc
        if person_id != revoked_person:
            raise Unauthenticated("Refresh token subject mismatch")

        # Issue the replacement pair. Roles remain empty until Step 5.
        tokens = await _issue_and_persist_refresh(session, person_id=person_id)

    return _to_wire(tokens)


class LogoutResponse(BaseModel):
    revoked_count: int


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    body: RefreshRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> LogoutResponse:
    """Revoke the refresh token presented — ends this session only.

    Access tokens remain valid until natural expiry (15 min max). That's
    an acceptable trade for stateless verification; full server-side
    revocation of access tokens would require a blocklist checked on
    every verify (added later if the exposure window becomes a concern).
    """
    try:
        claims = jwt.decode(
            body.refresh_token,
            get_settings().build_secret_provider().get("CIP_JWT_SIGNING_KEY"),
            algorithms=["HS256"],
            options={"verify_exp": False},  # allow revoking already-expired sessions
        )
    except jwt.InvalidTokenError as exc:
        raise Unauthenticated("Invalid refresh token") from exc

    async with admin_session(deps.session_factory) as session:
        result = await session.execute(
            text(
                "UPDATE tokens SET revoked = true "
                "WHERE token_hash = :jti AND kind = 'refresh' AND revoked = false "
                "RETURNING id"
            ),
            {"jti": claims.get("jti", "")},
        )
        return LogoutResponse(revoked_count=len(result.fetchall()))


# ---- Step 4: RBAC-guarded admin surface -----------------------------------


class AdminPingResponse(BaseModel):
    """Trivial payload for the admin-role probe endpoint."""

    person_id: uuid.UUID
    roles: list[str]


@router.get("/admin/ping", response_model=AdminPingResponse, tags=["admin"])
async def admin_ping(
    principal: Annotated[
        AuthenticatedPrincipal,
        Depends(require_role(*roles.TENANT_ADMIN_ROLES)),
    ],
) -> AdminPingResponse:
    """Return the caller's identity — accessible only to tenant-admin roles.

    Exists so Step 4 can prove the RBAC matrix end-to-end (each role x this
    endpoint) with real HTTP calls. Real admin endpoints (member management,
    role assignment, invitations) land with Step 5's memberships work.
    """
    return AdminPingResponse(person_id=principal.person_id, roles=list(principal.roles))


@router.post("/logout-all", response_model=LogoutResponse)
async def logout_all(
    deps: Annotated[Deps, Depends(get_deps)],
    principal: Annotated[AuthenticatedPrincipal, Depends(require_authenticated)],
) -> LogoutResponse:
    """Revoke every refresh token for the authenticated person.

    Requires a valid access token — you have to be currently authed to
    invalidate all sessions.
    """
    async with admin_session(deps.session_factory) as session:
        result = await session.execute(
            text(
                "UPDATE tokens SET revoked = true "
                "WHERE person_id = :pid AND kind = 'refresh' AND revoked = false "
                "RETURNING id"
            ),
            {"pid": principal.person_id},
        )
        return LogoutResponse(revoked_count=len(result.fetchall()))
