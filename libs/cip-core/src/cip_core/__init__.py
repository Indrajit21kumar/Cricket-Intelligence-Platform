"""cip-core — shared foundation library for CIP services.

Public API stabilised in M01 Step 2. Import from the top-level package; the
submodule layout is an implementation detail and may change.
"""

from cip_core import roles
from cip_core.audit import record as audit_record
from cip_core.auth import (
    ACCESS_TOKEN_TYPE,
    DEFAULT_ALGORITHM,
    REFRESH_TOKEN_TYPE,
    AuthenticatedPrincipal,
    require_authenticated,
    require_role,
    verify_token,
)
from cip_core.consent import (
    CONSENT_PROCESSING,
    CONSENT_SHARING,
    CONSENT_TRAINING,
    AccessDecision,
    TrainingConsentDecision,
    check_profile_access,
    has_active_consent,
    has_verified_guardianship,
    may_use_for_training,
    shared_active_tenants,
)
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
    "ACCESS_TOKEN_TYPE",
    "CONSENT_PROCESSING",
    "CONSENT_SHARING",
    "CONSENT_TRAINING",
    "CORRELATION_HEADER",
    "DEFAULT_ALGORITHM",
    "IDEMPOTENCY_HEADER",
    "MAX_KEY_LENGTH",
    "REFRESH_TOKEN_TYPE",
    "TENANT_HEADER",
    "AccessDecision",
    "AuthenticatedPrincipal",
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
    "TrainingConsentDecision",
    "Unauthenticated",
    "Unprocessable",
    "__version__",
    "audit_record",
    "build_provider",
    "check_profile_access",
    "correlation_scope",
    "get_correlation_id",
    "get_settings",
    "get_tenant_id",
    "has_active_consent",
    "has_verified_guardianship",
    "idempotency_key",
    "install",
    "may_use_for_training",
    "new_correlation_id",
    "require_authenticated",
    "require_idempotency_key",
    "require_role",
    "require_tenant_id",
    "roles",
    "shared_active_tenants",
    "tenant_scope",
    "verify_token",
]
