"""FastAPI middleware and exception handlers for the CIP contracts.

Wire this into every service via :func:`install`, which:

- Extracts (or generates) ``X-Correlation-ID`` on every request, binds it to
  :mod:`cip_core.context`, and echoes it back on the response.
- Extracts ``X-Tenant-ID`` when present and binds it to
  :mod:`cip_core.context`. Absence is *not* an error here — the enforcement
  point is the code that calls :func:`cip_core.context.require_tenant_id`.
- Installs exception handlers that convert every :class:`CIPError` and every
  uncaught exception into the standard :class:`ErrorEnvelope`.

The middleware is deliberately thin. Bind auth (M02) and metrics
instrumentation (Step 3) in additional layers on top.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from cip_core.context import correlation_scope, get_correlation_id, tenant_scope
from cip_core.errors import (
    BadRequest,
    CIPError,
    CIPErrorCode,
    ErrorBody,
    ErrorEnvelope,
    InternalError,
)

CORRELATION_HEADER = "X-Correlation-ID"
TENANT_HEADER = "X-Tenant-ID"


class CorrelationAndTenantMiddleware(BaseHTTPMiddleware):
    """Extract correlation + tenant identifiers from headers and bind context."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        # Correlation id: honour incoming header, generate if absent.
        incoming = request.headers.get(CORRELATION_HEADER)
        with correlation_scope(incoming) as correlation_id:
            tenant_value = request.headers.get(TENANT_HEADER)
            if tenant_value:
                try:
                    tenant_uuid = uuid.UUID(tenant_value)
                except ValueError as exc:
                    body = ErrorEnvelope(
                        error=ErrorBody(
                            code=CIPErrorCode.BAD_REQUEST,
                            message=f"Malformed {TENANT_HEADER} header",
                            details={"reason": str(exc)},
                            request_id=correlation_id,
                        )
                    )
                    err_response = JSONResponse(
                        status_code=400, content=body.model_dump(mode="json")
                    )
                    err_response.headers[CORRELATION_HEADER] = correlation_id
                    return err_response
                with tenant_scope(tenant_uuid):
                    response: Response = await call_next(request)
            else:
                response = await call_next(request)
            response.headers[CORRELATION_HEADER] = correlation_id
            return response


def _envelope_response(exc: CIPError) -> JSONResponse:
    request_id = get_correlation_id() or ""
    body = exc.to_envelope(request_id)
    response = JSONResponse(status_code=exc.http_status, content=body.model_dump(mode="json"))
    if request_id:
        response.headers[CORRELATION_HEADER] = request_id
    return response


async def cip_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler for :class:`CIPError` subclasses."""
    if not isinstance(exc, CIPError):
        # Only reachable if the handler is mis-registered — never in practice.
        raise TypeError(f"cip_error_handler received non-CIPError: {type(exc).__name__}")
    return _envelope_response(exc)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handler for FastAPI ``RequestValidationError`` — map to BadRequest."""
    if not isinstance(exc, RequestValidationError):
        raise TypeError(
            f"validation_error_handler received non-RequestValidationError: {type(exc).__name__}"
        )
    mapped = BadRequest("Request validation failed", details={"errors": exc.errors()})
    return _envelope_response(mapped)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback for any exception that isn't otherwise handled.

    The message and details are deliberately stripped — never leak internals
    to clients. Operators trace via the correlation id in the response header
    and in server-side logs.
    """
    mapped = InternalError("Internal server error")
    return _envelope_response(mapped)


def install(app: FastAPI) -> None:
    """Attach the middleware and exception handlers to a FastAPI app.

    Call this exactly once during app startup, before any routers are
    included. Order matters: middleware wraps everything, so contexts are
    set for the whole request lifecycle including the exception handlers.
    """
    app.add_middleware(CorrelationAndTenantMiddleware)
    app.add_exception_handler(CIPError, cip_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
