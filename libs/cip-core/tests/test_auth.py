"""Unit tests for :mod:`cip_core.auth` — JWT verification + require_role."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from cip_core.auth import (
    ACCESS_TOKEN_TYPE,
    DEFAULT_ALGORITHM,
    REFRESH_TOKEN_TYPE,
    require_authenticated,
    require_role,
    verify_token,
)
from cip_core.errors import Forbidden, Unauthenticated
from cip_core.settings import get_settings

TEST_SECRET = "test-signing-key-only-for-unit-tests-do-not-use"


@pytest.fixture(autouse=True)
def _pin_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the SecretProvider at a deterministic in-test key."""
    monkeypatch.setenv("CIP_JWT_SIGNING_KEY", TEST_SECRET)
    monkeypatch.setenv("CIP_SECRET_PROVIDER", "env")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _make_token(**overrides: object) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "sub": str(uuid.uuid4()),
        "type": ACCESS_TOKEN_TYPE,
        "roles": ["player"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    claims.update(overrides)
    return jwt.encode(claims, TEST_SECRET, algorithm=DEFAULT_ALGORITHM)


class TestVerifyToken:
    def test_valid_access_token(self) -> None:
        token = _make_token()
        claims = verify_token(token, token_type=ACCESS_TOKEN_TYPE)
        assert claims["type"] == ACCESS_TOKEN_TYPE

    def test_expired_rejected(self) -> None:
        past = int((datetime.now(UTC) - timedelta(hours=1)).timestamp())
        token = _make_token(exp=past)
        with pytest.raises(Unauthenticated, match="expired"):
            verify_token(token)

    def test_bad_signature_rejected(self) -> None:
        # Encode with a DIFFERENT secret — signature won't verify against
        # our configured signing key.
        now = datetime.now(UTC)
        bad = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "type": ACCESS_TOKEN_TYPE,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=15)).timestamp()),
            },
            "different-secret-than-the-verifier-uses",
            algorithm=DEFAULT_ALGORITHM,
        )
        with pytest.raises(Unauthenticated, match="invalid"):
            verify_token(bad)

    def test_wrong_type_rejected(self) -> None:
        token = _make_token(type=REFRESH_TOKEN_TYPE)
        with pytest.raises(Unauthenticated, match="access"):
            verify_token(token, token_type=ACCESS_TOKEN_TYPE)

    def test_missing_type_treated_as_wrong(self) -> None:
        # Building via the JWT lib bypasses our issuer; simulate a token
        # without a 'type' claim.
        now = datetime.now(UTC)
        token = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(minutes=15)).timestamp()),
            },
            TEST_SECRET,
            algorithm=DEFAULT_ALGORITHM,
        )
        with pytest.raises(Unauthenticated):
            verify_token(token)


class TestRequireAuthenticated:
    def test_no_header_rejected(self) -> None:
        with pytest.raises(Unauthenticated, match="Bearer"):
            require_authenticated(authorization=None)

    def test_wrong_scheme_rejected(self) -> None:
        with pytest.raises(Unauthenticated, match="Bearer"):
            require_authenticated(authorization="Basic abc123")

    def test_valid_bearer(self) -> None:
        person_id = uuid.uuid4()
        token = _make_token(sub=str(person_id), roles=["coach"])
        principal = require_authenticated(authorization=f"Bearer {token}")
        assert principal.person_id == person_id
        assert principal.roles == ("coach",)

    def test_malformed_subject_rejected(self) -> None:
        token = _make_token(sub="not-a-uuid")
        with pytest.raises(Unauthenticated, match="subject"):
            require_authenticated(authorization=f"Bearer {token}")

    def test_missing_roles_defaults_to_empty(self) -> None:
        token = _make_token(roles=[])
        principal = require_authenticated(authorization=f"Bearer {token}")
        assert principal.roles == ()

    def test_non_list_roles_rejected(self) -> None:
        token = _make_token(roles="not-a-list")
        with pytest.raises(Unauthenticated, match="roles"):
            require_authenticated(authorization=f"Bearer {token}")


class TestRequireRole:
    def _principal_with(self, *roles: str) -> object:
        token = _make_token(roles=list(roles))
        return require_authenticated(authorization=f"Bearer {token}")

    def test_matching_role_passes(self) -> None:
        dep = require_role("coach")
        principal = self._principal_with("coach")
        assert dep(principal) is principal

    def test_missing_role_forbidden(self) -> None:
        dep = require_role("academy_admin")
        principal = self._principal_with("player")
        with pytest.raises(Forbidden, match="Insufficient role"):
            dep(principal)

    def test_any_of_matches(self) -> None:
        dep = require_role("coach", "academy_admin", "org_admin")
        principal = self._principal_with("academy_admin")
        assert dep(principal) is principal

    def test_empty_roles_denied(self) -> None:
        dep = require_role("player")
        principal = self._principal_with()
        with pytest.raises(Forbidden):
            dep(principal)
