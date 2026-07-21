"""OAuth / SSO routes (M02 Step 7).

Two-leg flow:

- POST /v1/auth/oauth/{provider}/init — returns the provider's consent URL
  plus a CSRF ``state`` token (stored in Redis with a short TTL).
- POST /v1/auth/oauth/{provider}/callback — validates the state, exchanges
  the code for the verified identity, links-or-creates the person, and
  issues a CIP JWT pair equivalent to a password login (AC-M02-01 SSO).
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from cip_core import BadRequest, NotFound, audit_record
from cip_data import admin_session
from identity_service.deps import Deps, get_deps
from identity_service.domain.oauth import OAuthProvider, link_or_create_person
from identity_service.routes import TokenResponse, _issue_and_persist_refresh, _to_wire

oauth_router = APIRouter(prefix="/v1/auth/oauth", tags=["oauth"])

_STATE_PREFIX = "cip:oauth:state:"
_STATE_TTL = 600  # 10 minutes to complete the consent flow


class InitRequest(BaseModel):
    redirect_uri: str = Field(..., description="Where the provider returns the browser")


class InitResponse(BaseModel):
    authorization_url: str
    state: str


class CallbackRequest(BaseModel):
    code: str = Field(..., min_length=1)
    state: str = Field(..., min_length=1)
    redirect_uri: str


def _require_provider(deps: Deps, provider: str) -> OAuthProvider:
    p = deps.oauth_providers.get(provider)
    if p is None:
        raise NotFound(
            f"OAuth provider {provider!r} is not configured. "
            "Set its client id + secret to enable it."
        )
    return p


@oauth_router.post("/{provider}/init", response_model=InitResponse)
async def oauth_init(
    provider: str,
    body: InitRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> InitResponse:
    """Begin an SSO flow: mint a state token, return the consent URL."""
    prov = _require_provider(deps, provider)
    state = secrets.token_urlsafe(24)
    await deps.redis.set(f"{_STATE_PREFIX}{state}", provider, ex=_STATE_TTL)
    return InitResponse(
        authorization_url=prov.authorization_url(state=state, redirect_uri=body.redirect_uri),
        state=state,
    )


@oauth_router.post("/{provider}/callback", response_model=TokenResponse)
async def oauth_callback(
    provider: str,
    body: CallbackRequest,
    deps: Annotated[Deps, Depends(get_deps)],
) -> TokenResponse:
    """Complete an SSO flow: validate state, exchange code, issue CIP JWTs."""
    prov = _require_provider(deps, provider)

    # CSRF: the state must exist and belong to this provider. Consume it.
    stored = await deps.redis.get(f"{_STATE_PREFIX}{body.state}")
    if stored != provider:
        raise BadRequest("Invalid or expired OAuth state")
    await deps.redis.delete(f"{_STATE_PREFIX}{body.state}")

    identity = await prov.exchange_code(code=body.code, redirect_uri=body.redirect_uri)

    async with admin_session(deps.session_factory) as session:
        person_id = await link_or_create_person(session, provider=provider, identity=identity)
        tokens = await _issue_and_persist_refresh(session, person_id=person_id)
        await audit_record(
            session,
            action="auth.oauth_login",
            entity=f"person:{person_id}",
            actor=f"person:{person_id}",
            meta={"provider": provider},
        )

    return _to_wire(tokens)
