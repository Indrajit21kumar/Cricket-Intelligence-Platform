"""OAuth / SSO providers (M02 Step 7).

Design: providers sit behind the :class:`OAuthProvider` protocol so the
routes never know which vendor they're talking to. The concrete Google +
Microsoft providers use standard OIDC endpoints and only activate when
their client credentials are configured (via the SecretProvider). A
:class:`StubProvider` lets the integration tests exercise the full
init -> callback -> account-linking -> JWT flow without real vendor calls.

Account linking: on callback we look up a ``credentials`` row by
(provider, provider_subject). If found, the existing person logs in. If
not, a new person is created (status ``active`` — the provider already
verified the email) plus an ``oauth`` credential.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    """The verified identity a provider returns after code exchange."""

    subject: str  # the provider's stable user id ('sub')
    email: str


@runtime_checkable
class OAuthProvider(Protocol):
    """Every SSO provider implements this two-method surface."""

    name: str

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        """The URL to send the browser to, to start the consent flow."""
        ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthIdentity:
        """Exchange an auth code for the verified {subject, email}."""
        ...


class _OidcProvider:
    """Shared OIDC implementation for Google + Microsoft."""

    def __init__(
        self,
        *,
        name: str,
        client_id: str,
        client_secret: str,
        authorize_endpoint: str,
        token_endpoint: str,
        userinfo_endpoint: str,
        scope: str = "openid email",
    ) -> None:
        self.name = name
        self._client_id = client_id
        self._client_secret = client_secret
        self._authorize = authorize_endpoint
        self._token = token_endpoint
        self._userinfo = userinfo_endpoint
        self._scope = scope

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "scope": self._scope,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        query = "&".join(f"{k}={httpx.QueryParams({k: v})[k]}" for k, v in params.items())
        return f"{self._authorize}?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> OAuthIdentity:
        async with httpx.AsyncClient(timeout=10.0) as http:
            token_res = await http.post(
                self._token,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
                headers={"Accept": "application/json"},
            )
            token_res.raise_for_status()
            access_token = token_res.json()["access_token"]

            userinfo_res = await http.get(
                self._userinfo,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            userinfo_res.raise_for_status()
            info = userinfo_res.json()

        return OAuthIdentity(subject=str(info["sub"]), email=str(info["email"]))


def google_provider(client_id: str, client_secret: str) -> OAuthProvider:
    # nosec B106: token_endpoint is a public OIDC URL, not a password.
    return _OidcProvider(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        authorize_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        token_endpoint="https://oauth2.googleapis.com/token",  # nosec B106
        userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
    )


def microsoft_provider(client_id: str, client_secret: str) -> OAuthProvider:
    # nosec B106: token_endpoint is a public OIDC URL, not a password.
    return _OidcProvider(
        name="microsoft",
        client_id=client_id,
        client_secret=client_secret,
        authorize_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        token_endpoint="https://login.microsoftonline.com/common/oauth2/v2.0/token",  # nosec B106
        userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
    )


# --- account linking -------------------------------------------------------


async def link_or_create_person(
    session: AsyncSession,
    *,
    provider: str,
    identity: OAuthIdentity,
) -> uuid.UUID:
    """Return the person id for an OAuth identity, creating one if new.

    OAuth logins are always adult+active here (the provider verified the
    email). A minor-via-OAuth consent flow is a later refinement.
    """
    existing = await session.execute(
        text(
            "SELECT person_id FROM credentials "
            "WHERE type = 'oauth' AND provider = :p AND provider_subject = :s"
        ),
        {"p": provider, "s": identity.subject},
    )
    row = existing.first()
    if row is not None:
        return uuid.UUID(str(row[0]))

    # Maybe the email already exists (registered via password). Link the
    # OAuth credential to that person rather than creating a duplicate.
    by_email = await session.execute(
        text("SELECT id FROM persons WHERE email = :e"),
        {"e": identity.email},
    )
    email_row = by_email.first()
    if email_row is not None:
        person_id = uuid.UUID(str(email_row[0]))
    else:
        person_id = uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO persons (id, email, status, dob_band) "
                "VALUES (:id, :email, 'active', 'adult')"
            ),
            {"id": person_id, "email": identity.email},
        )

    await session.execute(
        text(
            "INSERT INTO credentials (id, person_id, type, provider, provider_subject) "
            "VALUES (:id, :pid, 'oauth', :p, :s)"
        ),
        {"id": uuid.uuid4(), "pid": person_id, "p": provider, "s": identity.subject},
    )
    return person_id
