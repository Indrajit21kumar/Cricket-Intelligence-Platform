"""Auth routes (register / verify / login) — M02 Step 2.

The demo endpoint from the scaffold template is removed; identity's real
API surface starts here. Later steps add:

- Step 3 — JWT issuance in ``login`` + refresh + logout
- Step 4 — RBAC on protected endpoints
- Step 5 — /v1/memberships + /v1/me
- Step 6 — /v1/consents + guardian flow
- Step 7 — /v1/auth/oauth/{provider}
- Step 8 — /v1/me/suspend, /v1/me/deletion-request, /v1/me/export-request
"""

from __future__ import annotations

import logging
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, EmailStr, Field, SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cip_core import BadRequest, Conflict, NotFound, Unauthenticated, require_idempotency_key
from cip_data import admin_session
from identity_service.deps import Deps, get_deps
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

# Process-wide hasher — safe to reuse (no per-request state).
_hasher = Hasher()

# Minor threshold — Book 0 §11.1 (COPPA/GDPR-K style bright line).
MINOR_MAX_AGE = 18


# --- request/response models ----------------------------------------------


class RegisterRequest(BaseModel):
    email: EmailStr
    password: SecretStr = Field(..., min_length=12, max_length=200)
    dob: date
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


class LoginResponse(BaseModel):
    person_id: uuid.UUID
    # M02 Step 2 returns a placeholder session identifier. Step 3 replaces
    # this shape with { access_token, refresh_token, token_type, expires_in }.
    session_placeholder: str = Field(
        ..., description="Replaced with real JWT access + refresh tokens in Step 3"
    )


# --- helpers ---------------------------------------------------------------


def _dob_band(dob: date) -> str:
    """Bucket the DOB into 'adult' or 'minor'."""
    today = date.today()
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return "adult" if years >= MINOR_MAX_AGE else "minor"


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

    log.info(
        "identity.verification.token_issued",
        extra={"person_id": str(person_id), "email": body.email},
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
    """Consume a verification token; flip the person to ``active``.

    Minors flip to ``pending_consent`` instead — a guardian consent
    (Step 6) is required before they can log in.
    """
    async with admin_session(deps.session_factory) as session:
        person_id = await claim_token(
            session,
            token_hash=hash_token(body.token),
            kind="verify",
        )
        if person_id is None:
            raise NotFound("Verification token is invalid, expired, or already used")

        person_result = await session.execute(
            text("SELECT dob_band FROM persons WHERE id = :id"),
            {"id": person_id},
        )
        row = person_result.first()
        if row is None:
            raise NotFound("Person no longer exists")
        dob_band = row[0]

        new_status = "pending_consent" if dob_band == "minor" else "active"
        await set_person_status(session, person_id=person_id, status=new_status)

    return VerifyEmailResponse(person_id=person_id, status=new_status)


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> LoginResponse:
    """Verify email + password; return a session placeholder.

    Same-shape 401 for both "unknown email" and "wrong password" so a caller
    cannot use response text to enumerate accounts. Timing side-channels
    are best-mitigated by argon2's constant-time verify + an unconditional
    hash op on lookup miss (added when Step 8 tightens the auth path).
    """
    invalid = Unauthenticated("Invalid email or password")

    async with admin_session(deps.session_factory) as session:
        person = await get_person_by_email(session, body.email)
        if person is None:
            raise invalid
        password_hash = await get_password_hash(session, person["id"])
        if password_hash is None:
            raise invalid
        if not _hasher.verify(password_hash, body.password.get_secret_value()):
            raise invalid
        if person["status"] == "pending_verification":
            raise BadRequest("Email is not yet verified")
        if person["status"] == "pending_consent":
            raise BadRequest("Guardian consent required before login")
        if person["status"] != "active":
            raise BadRequest(f"Account status is {person['status']!r}; cannot log in")

    return LoginResponse(
        person_id=person["id"],
        session_placeholder=str(uuid.uuid4()),
    )
