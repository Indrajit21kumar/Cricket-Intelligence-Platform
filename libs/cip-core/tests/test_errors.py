"""Tests for :mod:`cip_core.errors`."""

from __future__ import annotations

import pytest
from cip_core.errors import (
    BadRequest,
    CIPError,
    CIPErrorCode,
    Conflict,
    CrossTenantAccess,
    ErrorEnvelope,
    Forbidden,
    IdempotencyConflict,
    InternalError,
    MissingTenant,
    NotFound,
    RateLimited,
    ServiceUnavailable,
    Unauthenticated,
    Unprocessable,
)


class TestEnvelopeShape:
    def test_matches_book3_wire_shape(self) -> None:
        exc = BadRequest("bad input", details={"field": "email"})
        envelope = exc.to_envelope("corr-1")
        payload = envelope.model_dump(mode="json")
        assert set(payload) == {"error"}
        assert set(payload["error"]) == {"code", "message", "details", "request_id"}
        assert payload["error"]["code"] == "BAD_REQUEST"
        assert payload["error"]["message"] == "bad input"
        assert payload["error"]["details"] == {"field": "email"}
        assert payload["error"]["request_id"] == "corr-1"

    def test_details_optional(self) -> None:
        env = InternalError("kaboom").to_envelope("corr-9")
        assert env.error.details is None

    def test_json_serialisable(self) -> None:
        env = NotFound("player abc").to_envelope("corr-2")
        json_str = env.model_dump_json()
        assert '"code":"NOT_FOUND"' in json_str
        assert '"request_id":"corr-2"' in json_str

    def test_envelope_roundtrips(self) -> None:
        original = ErrorEnvelope.model_validate(
            {"error": {"code": "CONFLICT", "message": "x", "request_id": "c"}}
        )
        assert original.error.code is CIPErrorCode.CONFLICT
        assert original.error.details is None


@pytest.mark.parametrize(
    ("exc_cls", "http_status", "error_code"),
    [
        (BadRequest, 400, CIPErrorCode.BAD_REQUEST),
        (Unauthenticated, 401, CIPErrorCode.UNAUTHENTICATED),
        (Forbidden, 403, CIPErrorCode.FORBIDDEN),
        (NotFound, 404, CIPErrorCode.NOT_FOUND),
        (Conflict, 409, CIPErrorCode.CONFLICT),
        (IdempotencyConflict, 409, CIPErrorCode.IDEMPOTENCY_CONFLICT),
        (Unprocessable, 422, CIPErrorCode.UNPROCESSABLE),
        (RateLimited, 429, CIPErrorCode.RATE_LIMITED),
        (MissingTenant, 400, CIPErrorCode.MISSING_TENANT),
        (CrossTenantAccess, 403, CIPErrorCode.CROSS_TENANT_ACCESS),
        (InternalError, 500, CIPErrorCode.INTERNAL_ERROR),
        (ServiceUnavailable, 503, CIPErrorCode.SERVICE_UNAVAILABLE),
    ],
)
def test_error_hierarchy_matches_book3_status_map(
    exc_cls: type[CIPError], http_status: int, error_code: CIPErrorCode
) -> None:
    """Every concrete exception must have the right status code and error code."""
    assert exc_cls.http_status == http_status
    assert exc_cls.error_code == error_code
    assert issubclass(exc_cls, CIPError)


def test_cross_tenant_is_a_forbidden() -> None:
    """CrossTenantAccess extends Forbidden — a 403 with a specific reason."""
    assert issubclass(CrossTenantAccess, Forbidden)
    exc = CrossTenantAccess("not your row")
    assert exc.http_status == 403
    assert exc.error_code is CIPErrorCode.CROSS_TENANT_ACCESS
