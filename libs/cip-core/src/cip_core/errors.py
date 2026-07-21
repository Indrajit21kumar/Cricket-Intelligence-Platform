"""Standard error envelope and error taxonomy for every CIP API (Book 3 §3.1, §3.4).

The wire shape is fixed at ``{"error": {"code": str, "message": str,
"details": dict|None, "request_id": str}}``. Every response body from a CIP
service that indicates failure MUST use this shape; consumers can therefore
handle errors uniformly across the platform.

Domain code raises subclasses of :class:`CIPError`; the FastAPI exception
handler in :mod:`cip_core.middleware` converts them to the envelope. Any
uncaught exception is mapped to :class:`InternalError` — a 500 with a stable
``INTERNAL_ERROR`` code, no stack trace in the body, and the correlation id
so operators can trace the incident in logs.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class CIPErrorCode(StrEnum):
    """Canonical error codes surfaced across every CIP service.

    New codes are added here as new failure modes appear; codes are never
    renamed or repurposed once used (they're a contract with clients).
    """

    # Client-side
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHENTICATED = "UNAUTHENTICATED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    UNPROCESSABLE = "UNPROCESSABLE"
    RATE_LIMITED = "RATE_LIMITED"

    # Tenancy / auth invariants
    MISSING_TENANT = "MISSING_TENANT"
    CROSS_TENANT_ACCESS = "CROSS_TENANT_ACCESS"

    # Pipeline / graceful degradation (Book 2 §3.1)
    QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"
    PROVISIONAL_RESULT = "PROVISIONAL_RESULT"

    # Server-side
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class ErrorBody(BaseModel):
    """Inner error object of the envelope."""

    code: CIPErrorCode
    message: str
    details: dict[str, Any] | None = None
    request_id: str = Field(..., description="Correlation id for tracing")


class ErrorEnvelope(BaseModel):
    """The complete wire envelope: ``{"error": {...}}``."""

    error: ErrorBody


class CIPError(Exception):
    """Base class for domain errors that map to the standard envelope.

    Subclass this rather than raising bare exceptions from handler code; the
    exception handler in :mod:`cip_core.middleware` will convert any subclass
    to the correct HTTP status + envelope automatically.
    """

    #: HTTP status code returned when this error escapes to the response.
    http_status: int = 500
    #: Envelope error code. Subclasses MUST override.
    error_code: CIPErrorCode = CIPErrorCode.INTERNAL_ERROR

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_envelope(self, request_id: str) -> ErrorEnvelope:
        """Serialise the exception to the standard wire envelope."""
        return ErrorEnvelope(
            error=ErrorBody(
                code=self.error_code,
                message=self.message,
                details=self.details,
                request_id=request_id,
            )
        )


# --- concrete exception types -------------------------------------------------
# Named to read naturally in service code: ``raise NotFound("player X")``.


class BadRequest(CIPError):
    http_status = 400
    error_code = CIPErrorCode.BAD_REQUEST


class Unauthenticated(CIPError):
    http_status = 401
    error_code = CIPErrorCode.UNAUTHENTICATED


class Forbidden(CIPError):
    http_status = 403
    error_code = CIPErrorCode.FORBIDDEN


class NotFound(CIPError):
    http_status = 404
    error_code = CIPErrorCode.NOT_FOUND


class Conflict(CIPError):
    http_status = 409
    error_code = CIPErrorCode.CONFLICT


class IdempotencyConflict(CIPError):
    http_status = 409
    error_code = CIPErrorCode.IDEMPOTENCY_CONFLICT


class Unprocessable(CIPError):
    http_status = 422
    error_code = CIPErrorCode.UNPROCESSABLE


class RateLimited(CIPError):
    http_status = 429
    error_code = CIPErrorCode.RATE_LIMITED


class MissingTenant(CIPError):
    """No tenant context on a tenant-scoped request (AC-M01-02, negative case)."""

    http_status = 400
    error_code = CIPErrorCode.MISSING_TENANT


class CrossTenantAccess(Forbidden):
    """Attempt to read/write another tenant's data (AC-M01-02, negative case)."""

    error_code = CIPErrorCode.CROSS_TENANT_ACCESS


class InternalError(CIPError):
    http_status = 500
    error_code = CIPErrorCode.INTERNAL_ERROR


class ServiceUnavailable(CIPError):
    http_status = 503
    error_code = CIPErrorCode.SERVICE_UNAVAILABLE
