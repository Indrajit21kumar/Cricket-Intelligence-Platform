"""cip-core — shared foundation library for CIP services.

Public API stabilised in M01 Step 2. Import from the top-level package; the
submodule layout is an implementation detail and may change.
"""

from cip_core.context import (
    MissingTenantError,
    correlation_scope,
    get_correlation_id,
    get_tenant_id,
    new_correlation_id,
    require_tenant_id,
    tenant_scope,
)
from cip_core.errors import (
    BadRequest,
    CIPError,
    CIPErrorCode,
    Conflict,
    CrossTenantAccess,
    ErrorBody,
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
from cip_core.idempotency import (
    IDEMPOTENCY_HEADER,
    MAX_KEY_LENGTH,
    idempotency_key,
    require_idempotency_key,
)
from cip_core.middleware import (
    CORRELATION_HEADER,
    TENANT_HEADER,
    CorrelationAndTenantMiddleware,
    install,
)
from cip_core.secrets import (
    EnvSecretProvider,
    FileSecretProvider,
    SecretNotFoundError,
    SecretProvider,
    build_provider,
)
from cip_core.settings import Environment, Settings, get_settings

__version__ = "0.1.0"

__all__ = [
    "CORRELATION_HEADER",
    "IDEMPOTENCY_HEADER",
    "MAX_KEY_LENGTH",
    "TENANT_HEADER",
    "BadRequest",
    "CIPError",
    "CIPErrorCode",
    "Conflict",
    "CorrelationAndTenantMiddleware",
    "CrossTenantAccess",
    "EnvSecretProvider",
    "Environment",
    "ErrorBody",
    "ErrorEnvelope",
    "FileSecretProvider",
    "Forbidden",
    "IdempotencyConflict",
    "InternalError",
    "MissingTenant",
    "MissingTenantError",
    "NotFound",
    "RateLimited",
    "SecretNotFoundError",
    "SecretProvider",
    "ServiceUnavailable",
    "Settings",
    "Unauthenticated",
    "Unprocessable",
    "__version__",
    "build_provider",
    "correlation_scope",
    "get_correlation_id",
    "get_settings",
    "get_tenant_id",
    "idempotency_key",
    "install",
    "new_correlation_id",
    "require_idempotency_key",
    "require_tenant_id",
    "tenant_scope",
]
